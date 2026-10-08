from __future__ import annotations
from typing import Literal
import json
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import Direction
from .scene import SceneId
from .skill_plan import SkillName

Region = Literal["grasp_region", "placement_region", "button_surface"]

class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: SceneId

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
    reference: SceneId | None = None
    region: Region | None = None

class MoveParameters(Parameters):
    reference: SceneId | None = None
    region: Region | None = None
    motion_direction: Direction | None = None
    distance_m: float | None = Field(default=None, gt=0, le=2, allow_inf_nan=False)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema["oneOf"] = [
            {"required": ["region"], "properties": {"region": {"type": "string"}},
             "not": {"anyOf": [{"required": ["motion_direction"]}, {"required": ["distance_m"]}]}},
            {"required": ["motion_direction", "distance_m"],
             "properties": {"motion_direction": {"type": "string"}, "distance_m": {"type": "number"}},
             "not": {"required": ["region"]}},
        ]
        return schema

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
    reference: SceneId | None = None
    region: Region | None = None

class PushParameters(Parameters):
    reference: SceneId | None = None
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

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        variants = schema["properties"]["parameters"]["anyOf"]
        by_title = {handler.resolve_ref_schema(ref)["title"]: ref for ref in variants}
        schema["allOf"] = [
            {"if": {"properties": {"skill_name": {"const": skill.value}}},
             "then": {"properties": {"parameters": by_title[model.__name__]}}}
            for skill, model in PARAMETER_TYPES.items()
        ]
        return schema

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

class CommandPlacementTarget(BaseModel):
    """Concrete Control target; never reuse semantic Task PlacementTarget."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["container_interior", "support_surface", "relative_object", "free_space"]
    reference: SceneId | None = None
    relation: str | None = None

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.kind == "relative_object" and (self.reference is None or not self.relation):
            raise ValueError("relative_object placement requires reference and relation")
        if self.kind == "container_interior" and self.relation not in {None, "inside"}:
            raise ValueError("container placement relation must be inside")
        if self.kind == "free_space" and self.relation is not None:
            raise ValueError("free_space placement allows an optional support reference, not a relation")
        return self

class CommandOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    semantic_intent: str = Field(min_length=1)
    placement_target: CommandPlacementTarget | None = None

class CommandsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    request_id: str
    scene_id: SceneId
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
    holding_object: SceneId | None = None


def canonical_commands(commands: CommandsFile) -> dict:
    """The sole wire representation. Validate models and the public schema."""
    payload = commands.model_dump(mode="json", exclude_none=True)
    CommandsFile.model_validate(payload)
    json.dumps(payload, allow_nan=False)
    Draft202012Validator(CommandsFile.model_json_schema()).validate(payload)
    return payload
