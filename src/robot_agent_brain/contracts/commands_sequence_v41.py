"""Per-arm sequences with explicit logical dependencies, not physical scheduling.

The file does not contain an expected operation set. Coverage against the
original request must therefore also be checked by the builder, not inferred
from the commands alone.
"""
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHARED_METADATA = frozenset({
    "execution_policy", "resource_groups", "hold_constraints", "sync_groups",
    "parallel_group", "parallel_required", "same_arm_group",
    "conditions", "preconditions", "effects",
})


class SequenceStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_shared_metadata(cls, value):
        if isinstance(value, dict):
            forbidden = SHARED_METADATA.intersection(value)
            if forbidden:
                raise ValueError("commands_v41_shared_metadata_forbidden: " + ",".join(sorted(forbidden)))
        return value


class SequenceCommand(SequenceStrictModel):
    command_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    arm: Literal["left", "right"]
    skill_name: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class CommandsFileV41(SequenceStrictModel):
    schema_version: Literal["4.1"] = "4.1"
    request_id: str = Field(min_length=1)
    scene_id: int = Field(ge=0)
    scene_version: int = Field(ge=0)
    scene_digest: str = Field(min_length=1)
    robot_setup_revision: int = Field(ge=0)
    skill_contract_revision: str = Field(min_length=1)
    commands: list[SequenceCommand] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sequences(self):
        by_id = {command.command_id: command for command in self.commands}
        if len(by_id) != len(self.commands):
            raise ValueError("commands_v41_duplicate_command_id")
        successors = {key: [] for key in by_id}
        indegree = {}
        for command in self.commands:
            dependencies = command.depends_on
            if (len(set(dependencies)) != len(dependencies)
                    or any(key not in by_id or key == command.command_id for key in dependencies)):
                raise ValueError("commands_v41_dependency_reference_invalid")
            indegree[command.command_id] = len(dependencies)
            for key in dependencies:
                successors[key].append(command.command_id)
        ready = deque(key for key, degree in indegree.items() if degree == 0)
        ancestors = {}
        while ready:
            key = ready.popleft()
            dependencies = by_id[key].depends_on
            ancestors[key] = set(dependencies)
            for predecessor in dependencies:
                ancestors[key].update(ancestors[predecessor])
            for successor in successors[key]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
        if len(ancestors) != len(by_id):
            raise ValueError("commands_v41_dependency_cycle")
        previous_by_arm, operation_arms = {}, {}
        closed_operations, active_by_arm = set(), {}
        for command in self.commands:
            arm, operation = command.arm, command.operation_id
            if operation_arms.setdefault(operation, arm) != arm:
                raise ValueError("commands_v41_operation_arm_changed")
            previous = previous_by_arm.get(arm)
            if previous is not None and previous not in ancestors[command.command_id]:
                raise ValueError("commands_v41_same_arm_sequence_invalid")
            active = active_by_arm.get(arm)
            if active != operation:
                if operation in closed_operations:
                    raise ValueError("commands_v41_operation_sequence_invalid")
                if active is not None:
                    closed_operations.add(active)
                active_by_arm[arm] = operation
            previous_by_arm[arm] = command.command_id
        return self


def canonical_commands_v41(commands: CommandsFileV41) -> dict:
    payload = commands.model_dump(mode="json", exclude_none=True)
    CommandsFileV41.model_validate(payload)
    return payload
