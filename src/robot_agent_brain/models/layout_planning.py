"""Restricted custom pattern draft: no assets, IDs, poses or operations."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.arrangement import ArrangementPattern


class LayoutPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=1000)
    requested_count: int = Field(ge=1, le=1000)


class NormalizedPathPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    u: float = Field(ge=0, le=1, allow_inf_nan=False)
    v: float = Field(ge=0, le=1, allow_inf_nan=False)


class LayoutPatternDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: list[NormalizedPathPoint] = Field(min_length=2, max_length=512)

    @model_validator(mode="after")
    def simple_path(self):
        ArrangementPattern(kind="custom", path=self.points())
        return self

    def points(self):
        return [(point.u, point.v) for point in self.path]
