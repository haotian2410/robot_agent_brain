from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import PlacementTarget

class LocateParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str

class GraspParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str

class ReleaseParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    reference: str | None = None
    region: str | None = None

class MoveParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    reference: str | None = None
    region: str | None = None
    motion_direction: str | None = None
    distance_m: float | None = Field(default=None, gt=0, le=2)

class PressParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    region: str | None = None

class PullPushParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    reference: str | None = None
    region: str | None = None


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    source_skill_step_id: str
    operation_id: str
    skill_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def forbid_physical_execution_fields(self):
        forbidden = {"anchor", "pose", "xyz", "trajectory", "ik_method", "planning_method", "joint_angles", "joint_positions", "quaternion", "waypoints", "path", "velocity_scale", "acceleration_scale", "cartesian_step", "collision_margin", "ee_pose", "tcp_pose"}
        overlap = forbidden & set(self.parameters)
        if overlap:
            raise ValueError(f"Brain command contains physical fields: {sorted(overlap)}")
        if self.skill_name == "move":
            region = self.parameters.get("region")
            directional = {"motion_direction", "distance_m"} & set(self.parameters)
            if region is not None and directional:
                raise ValueError("command_semantic_invalid: move region and directional parameters are mutually exclusive")
            if region is None and directional != {"motion_direction", "distance_m"}:
                raise ValueError("command_semantic_invalid: directional move requires direction and distance")
            MoveParameters.model_validate(self.parameters)
        elif self.skill_name == "locate":
            LocateParameters.model_validate(self.parameters)
        elif self.skill_name == "grasp":
            GraspParameters.model_validate(self.parameters)
        elif self.skill_name == "release":
            ReleaseParameters.model_validate(self.parameters)
        elif self.skill_name == "press":
            PressParameters.model_validate(self.parameters)
        elif self.skill_name in {"pull", "push"}:
            PullPushParameters.model_validate(self.parameters)
        return self


class CommandOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    semantic_intent: str
    placement_target: PlacementTarget | None = None


class CommandsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    request_id: str
    scene_id: str
    scene_version: int
    robot: str
    operations: list[CommandOperation]
    commands: list[Command]

    @model_validator(mode="after")
    def validate_consistency(self):
        if len({item.command_id for item in self.commands}) != len(self.commands):
            raise ValueError("commands command_id must be unique")
        operation_ids = {item.operation_id for item in self.operations}
        if any(item.operation_id not in operation_ids for item in self.commands):
            raise ValueError("command operation_id is not declared")
        return self


class CommandFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    status: Literal["success", "failed"]


class ExecutionFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: Literal["success", "failed", "partial"]
    commands: list[CommandFeedback]
    holding_object: str | None = None
