"""Staged dual-arm wire contract. Pour awaits the Control skill specification.

Structural validation here does not establish physical safety or replace the
coordinated planner/state validator. Existing single-arm output remains v2.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .commands import Command, CommandOperation
from .robot_setup import RobotSetup
from .scene import SceneId
from .skill_plan import SkillName

DualArm = Literal["left", "right"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HoldingCondition(StrictModel):
    predicate: Literal["holding"]
    arm: DualArm
    object_id: SceneId


class EmptyCondition(StrictModel):
    predicate: Literal["gripper_empty"]
    arm: DualArm


class LocatedCondition(StrictModel):
    predicate: Literal["located"]
    object_id: SceneId


class RegionCondition(StrictModel):
    predicate: Literal["at_region"]
    arm: DualArm
    object_id: SceneId
    region: Literal["grasp_region", "placement_region"]


Condition = Annotated[HoldingCondition | EmptyCondition | LocatedCondition | RegionCondition,
                      Field(discriminator="predicate")]


class DualCommand(Command):
    skill_name: Literal[SkillName.LOCATE, SkillName.MOVE, SkillName.GRASP, SkillName.RELEASE]


class ArmSlots(StrictModel):
    # Required keys, optional actions: null means keep the existing arm state.
    left: DualCommand | None
    right: DualCommand | None

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema["not"] = {"properties": {"left": {"type": "null"}, "right": {"type": "null"}},
                         "required": ["left", "right"]}
        return schema

    @model_validator(mode="after")
    def nonempty(self):
        if self.left is None and self.right is None:
            raise ValueError("dual_stage_empty")
        return self


class CoordinatedStep(StrictModel):
    step_id: str = Field(min_length=1)
    semantic_intent: str = Field(min_length=1)
    preconditions: list[Condition] = Field(default_factory=list)
    invariants: list[Condition] = Field(default_factory=list)
    arms: ArmSlots


class ExecutionPolicy(StrictModel):
    between_steps: Literal["barrier"] = "barrier"
    within_step: Literal["parallel"] = "parallel"
    null_arm: Literal["maintain_state"] = "maintain_state"
    on_failure: Literal["stop_no_automatic_replay"] = "stop_no_automatic_replay"


class DualOperation(CommandOperation):
    task_type: Literal["locate", "move", "grasp", "release", "pick_and_place"]
    source: SceneId | None = None
    destination: SceneId | None = None
    target: SceneId | None = None
    arm: DualArm
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    parallel_required: bool = False


class HoldConstraint(StrictModel):
    kind: Literal["hold_during_operation", "hold_until_operation"]
    holder_arm: DualArm
    object_id: SceneId
    while_operation: str
    holder_operation: str | None = None
    region_object_id: SceneId | None = None
    region: Literal["placement_region"] | None = None

    @model_validator(mode="after")
    def complete_milestone(self):
        if (self.region is None) != (self.region_object_id is None):
            raise ValueError("dual_hold_region_incomplete")
        if self.kind == "hold_until_operation" and (self.holder_operation is None or self.region is None):
            raise ValueError("dual_hold_milestone_incomplete")
        if self.kind == "hold_during_operation" and self.holder_operation is not None:
            raise ValueError("dual_hold_unexpected_holder_operation")
        return self


class CommandsFileV3(StrictModel):
    schema_version: Literal["3.0"] = "3.0"
    request_id: str = Field(min_length=1)
    scene_id: SceneId
    scene_version: int = Field(strict=True, ge=0)
    robot_setup_revision: int = Field(strict=True, ge=1)
    robot_setup: RobotSetup
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    operations: list[DualOperation] = Field(min_length=1)
    steps: list[CoordinatedStep] = Field(min_length=1)
    hold_constraints: list[HoldConstraint] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_ids_and_assignments(self):
        if self.robot_setup.mode != "dual":
            raise ValueError("commands_v3_requires_dual_setup")
        actions = [(side, command, i) for i, step in enumerate(self.steps)
                   for side, command in (("left", step.arms.left), ("right", step.arms.right)) if command is not None]
        for identifiers in ([step.step_id for step in self.steps],
                            [command.command_id for _, command, _ in actions],
                            [command.source_skill_step_id for _, command, _ in actions],
                            [operation.operation_id for operation in self.operations]):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("commands_v3_duplicate_identifier")
        operations = {operation.operation_id: operation for operation in self.operations}
        for constraint in self.hold_constraints:
            other = operations.get(constraint.while_operation)
            if other is None or other.arm == constraint.holder_arm:
                raise ValueError("dual_hold_operation_or_arm_invalid")
            if constraint.holder_operation is not None:
                holder = operations.get(constraint.holder_operation)
                if holder is None or holder.arm != constraint.holder_arm:
                    raise ValueError("dual_hold_holder_invalid")
        if {command.operation_id for _, command, _ in actions} != set(operations):
            raise ValueError("commands_v3_operation_coverage_mismatch")
        stages = {identifier: [i for _, command, i in actions if command.operation_id == identifier]
                  for identifier in operations}
        for side, command, _ in actions:
            if operations[command.operation_id].arm != side:
                raise ValueError("commands_v3_arm_assignment_mismatch")
        for operation in self.operations:
            for dependency in operation.depends_on:
                if dependency not in stages or max(stages[dependency]) >= min(stages[operation.operation_id]):
                    raise ValueError("commands_v3_dependency_order_invalid")
        return self


def canonical_commands_v3(commands: CommandsFileV3) -> dict:
    import json
    from jsonschema import Draft202012Validator
    payload = commands.model_dump(mode="json", exclude_none=True)
    # Keep compact parameter dictionaries, but never omit the two arm slots.
    for stage, model in zip(payload["steps"], commands.steps):
        for side in ("left", "right"):
            if getattr(model.arms, side) is None:
                stage["arms"][side] = None
    CommandsFileV3.model_validate(payload)
    json.dumps(payload, allow_nan=False)
    Draft202012Validator(CommandsFileV3.model_json_schema()).validate(payload)
    return payload
