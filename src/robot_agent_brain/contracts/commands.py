from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import PlacementTarget


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    source_skill_step_id: str
    operation_id: str
    skill_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def forbid_physical_execution_fields(self):
        forbidden = {"anchor", "pose", "xyz", "trajectory", "ik_method", "planning_method"}
        overlap = forbidden & set(self.parameters)
        if overlap:
            raise ValueError(f"Brain command contains physical fields: {sorted(overlap)}")
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

