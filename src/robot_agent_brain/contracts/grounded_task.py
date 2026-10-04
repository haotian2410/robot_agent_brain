from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import Operation


class GroundedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    semantic_name: str
    scene_object_id: str
    scene_object_ids: list[str] = Field(default_factory=list)
    asset_id: str
    category: str

    @model_validator(mode="after")
    def normalize_members(self):
        if not self.scene_object_ids:
            self.scene_object_ids = [self.scene_object_id]
        elif self.scene_object_id not in self.scene_object_ids:
            self.scene_object_ids.insert(0, self.scene_object_id)
        return self


class GroundedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str
    entities: list[GroundedEntity]
    operations: list[Operation]
    scene_id: str
    scene_version: int

    @model_validator(mode="after")
    def unique_bindings(self):
        ids = [item.entity_id for item in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("grounded entity id must be unique")
        return self
