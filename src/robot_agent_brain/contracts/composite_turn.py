"""Audit record for a scene-layout/edit phase followed by robot planning."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .turn import BrainTurn


class CompositeTask(BaseModel):
    """Already-understood phases, never strings that require another U call."""
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1)
    phases: list[BrainTurn] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def scene_then_robot(self):
        if self.phases[-1].turn_kind != "robot_task":
            raise ValueError("composite_robot_phase_required")
        if any(phase.turn_kind not in {"scene_edit", "scene_layout"} for phase in self.phases[:-1]):
            raise ValueError("composite_scene_phase_required")
        if any(phase.status != "accepted" for phase in self.phases):
            raise ValueError("composite_unresolved_phase")
        return self


class CompositePhase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase_id: str = Field(min_length=1)
    kind: Literal["scene_layout", "scene_edit", "robot_task", "scene_query"]
    status: Literal["pending", "committed", "planned", "executed", "failed", "skipped"]
    request_id: str = Field(min_length=1)
    scene_version_before: int | None = None
    scene_version_after: int | None = None
    scene_digest_before: str | None = None
    scene_digest_after: str | None = None
    error_code: str | None = None


class CompositeTurnRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str = Field(min_length=1)
    phases: list[CompositePhase] = Field(min_length=1)
    atomic: bool = False
