"""Provider-independent atomic operation IR used before DAG emission."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AtomicOperationIR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1)
    kind: Literal["pick_and_place", "open", "close", "press", "move", "release", "grasp", "locate", "search"]
    source_object_id: int | None = Field(default=None, ge=0)
    destination_object_id: int | None = Field(default=None, ge=0)
    reference_object_id: int | None = Field(default=None, ge=0)
    relation: str | None = None
    arm: Literal["left", "right"] | None = None
    depends_on: list[str] = Field(default_factory=list)
