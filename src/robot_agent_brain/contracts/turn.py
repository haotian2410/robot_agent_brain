from __future__ import annotations
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import TaskIntent

class TurnStatus(StrEnum):
    ACCEPTED = "accepted"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED_TASK = "unsupported_task"

class TurnKind(StrEnum):
    ROBOT_TASK = "robot_task"
    SCENE_EDIT = "scene_edit"
    SCENE_QUERY = "scene_query"
    SESSION_CONTROL = "session_control"
    UNSUPPORTED_TASK = "unsupported_task"

class SceneEditIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["add", "remove", "update"]
    semantic_name: str
    category: str
    count: int = Field(default=1, ge=1)
    relation: str | None = None
    reference: str | None = None
    properties: dict[str, str | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def paired_relation(self):
        if (self.relation is None) != (self.reference is None):
            raise ValueError("task_semantic_invalid: scene edit relation/reference must be paired")
        return self

class SceneQueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_type: Literal["count", "existence", "position", "state"]
    semantic_name: str | None = None
    category: str | None = None
    referent_scene_object_id: str | None = None

class SessionControlIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "close"]

class BrainTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TurnStatus
    turn_kind: TurnKind
    instruction: str
    task_intent: TaskIntent | None = None
    scene_edit: SceneEditIntent | None = None
    scene_query: SceneQueryIntent | None = None
    session_control: SessionControlIntent | None = None

    @model_validator(mode="after")
    def one_payload(self):
        payloads = {
            TurnKind.ROBOT_TASK: self.task_intent,
            TurnKind.SCENE_EDIT: self.scene_edit,
            TurnKind.SCENE_QUERY: self.scene_query,
            TurnKind.SESSION_CONTROL: self.session_control,
        }
        if self.status != TurnStatus.ACCEPTED:
            if any(value is not None for value in payloads.values()):
                raise ValueError("rejected turn must not contain actionable payloads")
            return self
        if self.turn_kind == TurnKind.UNSUPPORTED_TASK:
            raise ValueError("unsupported turn must have unsupported_task status")
        if self.turn_kind in payloads and payloads[self.turn_kind] is None:
            raise ValueError("turn payload is missing")
        if self.turn_kind in payloads and sum(value is not None for value in (self.task_intent, self.scene_edit, self.scene_query, self.session_control)) != 1:
            raise ValueError("turn must contain exactly one payload")
        return self
