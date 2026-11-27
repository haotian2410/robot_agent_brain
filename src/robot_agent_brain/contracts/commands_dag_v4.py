"""Commands DAG v4: Brain-owned logical dependencies, Control-owned physics."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DagStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DagExecutionPolicy(DagStrictModel):
    scheduler: Literal["dependency_dag"] = "dependency_dag"
    parallel: Literal["allowed", "disabled"] = "allowed"
    on_failure: Literal["stop_dependents_continue_independent", "stop_all"] = "stop_dependents_continue_independent"


class DagCommand(DagStrictModel):
    command_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    arm: Literal["left", "right"]
    skill_name: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class ResourceGroup(DagStrictModel):
    resource_id: str = Field(min_length=1)
    mode: Literal["exclusive", "shared"] = "exclusive"
    command_ids: list[str] = Field(min_length=1)


class HoldConstraintV4(DagStrictModel):
    object_id: int = Field(ge=0)
    holder_arm: Literal["left", "right"]
    until_command_id: str = Field(min_length=1)
    # None anchors the constraint to verified input runtime state.
    after_command_id: str | None = Field(default=None, min_length=1)
    region_object_id: int | None = Field(default=None, ge=0)
    region: Literal["placement_region"] | None = None

    @model_validator(mode="after")
    def region_pair(self):
        if (self.region_object_id is None) != (self.region is None):
            raise ValueError("commands_v4_hold_region_incomplete")
        return self


class SyncGroup(DagStrictModel):
    sync_id: str = Field(min_length=1)
    command_ids: list[str] = Field(min_length=2)


class CommandsFileV4(DagStrictModel):
    schema_version: Literal["4.0"] = "4.0"
    request_id: str = Field(min_length=1)
    scene_id: int = Field(ge=0)
    scene_version: int = Field(ge=0)
    scene_digest: str = Field(min_length=1)
    robot_setup_revision: int = Field(ge=0)
    skill_contract_revision: str = Field(min_length=1)
    execution_policy: DagExecutionPolicy = Field(default_factory=DagExecutionPolicy)
    commands: list[DagCommand] = Field(min_length=1)
    resource_groups: list[ResourceGroup] = Field(default_factory=list)
    hold_constraints: list[HoldConstraintV4] = Field(default_factory=list)
    sync_groups: list[SyncGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self):
        command_ids = [command.command_id for command in self.commands]
        operation_ids = [command.operation_id for command in self.commands]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("commands_v4_duplicate_command_id")
        if not set(operation_ids):
            raise ValueError("commands_v4_operation_missing")
        known = set(command_ids)
        graph = {command.command_id: set(command.depends_on) for command in self.commands}
        if any(dep not in known or dep == command_id for command_id, deps in graph.items() for dep in deps):
            raise ValueError("commands_v4_dependency_reference_invalid")
        visiting, visited = set(), set()
        def visit(node):
            if node in visiting:
                raise ValueError("commands_v4_dependency_cycle")
            if node in visited:
                return
            visiting.add(node)
            for dep in graph[node]:
                visit(dep)
            visiting.remove(node)
            visited.add(node)
        for node in graph:
            visit(node)
        def ancestors(node):
            found, frontier = set(), list(graph[node])
            while frontier:
                item = frontier.pop()
                if item not in found:
                    found.add(item)
                    frontier.extend(graph[item])
            return found
        grouped = {}
        for command in self.commands:
            grouped.setdefault(command.arm, []).append(command.command_id)
        for arm, ids in grouped.items():
            # Same-arm commands must be ordered unless an explicit dependency
            # already orders them transitively; they cannot run concurrently.
            for previous, current in zip(ids, ids[1:]):
                if previous not in graph[current]:
                    # A transitive dependency is also acceptable.
                    ancestors = set()
                    frontier = list(graph[current])
                    while frontier:
                        item = frontier.pop()
                        if item in graph and item not in ancestors:
                            ancestors.add(item); frontier.extend(graph[item])
                    if previous not in ancestors:
                        raise ValueError("commands_v4_same_arm_parallel_forbidden")
        referenced = set(cid for group in self.resource_groups for cid in group.command_ids)
        if not referenced <= known:
            raise ValueError("commands_v4_resource_command_missing")
        if len({group.resource_id for group in self.resource_groups}) != len(self.resource_groups):
            raise ValueError("commands_v4_duplicate_resource")
        if any(len(set(group.command_ids)) != len(group.command_ids) for group in self.resource_groups):
            raise ValueError("commands_v4_duplicate_resource_command")
        if len({group.sync_id for group in self.sync_groups}) != len(self.sync_groups):
            raise ValueError("commands_v4_duplicate_sync")
        arms = {command.command_id: command.arm for command in self.commands}
        for group in self.sync_groups:
            if not set(group.command_ids) <= known:
                raise ValueError("commands_v4_sync_command_missing")
            if len(set(group.command_ids)) != len(group.command_ids) or len({arms[cid] for cid in group.command_ids}) != len(group.command_ids):
                raise ValueError("commands_v4_sync_same_arm")
            if any(set(group.command_ids) & ancestors(cid) for cid in group.command_ids):
                raise ValueError("commands_v4_sync_dependency_conflict")
            if any(resource.mode == "exclusive" and len(set(resource.command_ids) & set(group.command_ids)) > 1
                   for resource in self.resource_groups):
                raise ValueError("commands_v4_sync_resource_conflict")
        for hold in self.hold_constraints:
            if hold.until_command_id not in known:
                raise ValueError("commands_v4_hold_command_missing")
            if arms[hold.until_command_id] == hold.holder_arm:
                raise ValueError("commands_v4_hold_endpoint_same_arm")
            if hold.after_command_id is not None:
                if hold.after_command_id not in known or arms[hold.after_command_id] != hold.holder_arm:
                    raise ValueError("commands_v4_hold_anchor_invalid")
                if hold.after_command_id not in ancestors(hold.until_command_id):
                    raise ValueError("commands_v4_hold_anchor_not_ordered")
        owners = {}
        for hold in self.hold_constraints:
            if hold.object_id in owners and owners[hold.object_id] != hold.holder_arm:
                raise ValueError("commands_v4_hold_owner_conflict")
            owners[hold.object_id] = hold.holder_arm
        return self


def canonical_commands_v4(commands: CommandsFileV4) -> dict:
    payload = commands.model_dump(mode="json", exclude_none=True)
    CommandsFileV4.model_validate(payload)
    return payload
