from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import Direction, PlacementTarget
from .skill_plan import SkillName

Region = Literal["grasp_region", "placement_region", "button_surface"]

class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1)

    # Compatibility for clients of the v2 JSON-shaped Python API.
    def __getitem__(self, key):
        return self.model_dump(exclude_none=True)[key]

    def __contains__(self, key):
        return key in self.model_dump(exclude_none=True)

class LocateParameters(Parameters):
    pass

class GraspParameters(Parameters):
    pass

class ReleaseParameters(Parameters):
    reference: str | None = None
    region: Region | None = None

class MoveParameters(Parameters):
    reference: str | None = None
    region: Region | None = None
    motion_direction: Direction | None = None
    distance_m: float | None = Field(default=None, gt=0, le=2, allow_inf_nan=False)

    @model_validator(mode="after")
    def exclusive_modes(self):
        if self.region is not None:
            if self.motion_direction is not None or self.distance_m is not None:
                raise ValueError("command_semantic_invalid: region and displacement are exclusive")
        elif self.motion_direction is None or self.distance_m is None:
            raise ValueError("command_semantic_invalid: directional move requires direction and distance")
        return self

class PressParameters(Parameters):
    region: Region | None = None

class PullParameters(Parameters):
    reference: str | None = None
    region: Region | None = None

class PushParameters(Parameters):
    reference: str | None = None
    region: Region | None = None

PARAMETER_TYPES = {
    SkillName.LOCATE: LocateParameters, SkillName.MOVE: MoveParameters,
    SkillName.GRASP: GraspParameters, SkillName.RELEASE: ReleaseParameters,
    SkillName.PRESS: PressParameters, SkillName.PULL: PullParameters, SkillName.PUSH: PushParameters,
}

class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1)
    source_skill_step_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    skill_name: SkillName
    parameters: LocateParameters | MoveParameters | GraspParameters | ReleaseParameters | PressParameters | PullParameters | PushParameters

    @model_validator(mode="before")
    @classmethod
    def typed_parameters(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        kind = SkillName(data["skill_name"])
        params = data.get("parameters", {})
        if isinstance(params, BaseModel):
            params = params.model_dump(exclude_none=True)
        data["parameters"] = PARAMETER_TYPES[kind].model_validate(params)
        return data

class CommandOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    semantic_intent: str = Field(min_length=1)
    placement_target: PlacementTarget | None = None

class CommandsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    request_id: str
    scene_id: str
    scene_version: int = Field(ge=0)
    robot: str
    operations: list[CommandOperation]
    commands: list[Command]

    @model_validator(mode="after")
    def validate_consistency(self):
        for values in ([c.command_id for c in self.commands],
                       [c.source_skill_step_id for c in self.commands],
                       [o.operation_id for o in self.operations]):
            if len(values) != len(set(values)):
                raise ValueError("command and operation identifiers must be unique")
        order = {o.operation_id: i for i, o in enumerate(self.operations)}
        if any(c.operation_id not in order for c in self.commands):
            raise ValueError("command operation_id is not declared")
        indices = [order[c.operation_id] for c in self.commands]
        if indices != sorted(indices):
            raise ValueError("commands operation order mismatch")
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
