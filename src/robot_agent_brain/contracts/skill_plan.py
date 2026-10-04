from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class SkillName(StrEnum):
    LOCATE = "locate"
    MOVE = "move"
    GRASP = "grasp"
    RELEASE = "release"
    PRESS = "press"
    PULL = "pull"
    PUSH = "push"


class SkillStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    operation_id: str
    skill_name: SkillName
    target_entity: str | None = None
    reference_entity: str | None = None
    region: str | None = None


class SkillPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[SkillStep] = Field(default_factory=list)

