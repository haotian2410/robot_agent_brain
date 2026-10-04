from __future__ import annotations

from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transform(StrictModel):
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    quaternion_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


class SceneObject(StrictModel):
    scene_object_id: str
    asset_id: str
    semantic_name: str
    category: str
    transform: Transform = Field(default_factory=Transform)
    properties: dict[str, Any] = Field(default_factory=dict)


class SceneConfig(StrictModel):
    schema_version: str = "1.0"
    scene_id: str
    scene_version: int = Field(default=0, ge=0)
    robot: str | None = None
    objects: list[SceneObject] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_objects(self):
        ids = [item.scene_object_id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_object_id must be unique")
        return self


class PatchAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    UPDATE_TRANSFORM = "update_transform"
    UPDATE_PROPERTY = "update_property"


class ScenePatchOperation(StrictModel):
    action: PatchAction
    scene_object_id: str
    object: SceneObject | None = None
    transform: Transform | None = None
    properties: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        required = {
            PatchAction.ADD: self.object,
            PatchAction.UPDATE_TRANSFORM: self.transform,
            PatchAction.UPDATE_PROPERTY: self.properties,
        }
        if self.action in required and required[self.action] is None:
            raise ValueError(f"{self.action.value} patch payload is missing")
        if self.action == PatchAction.ADD and self.object.scene_object_id != self.scene_object_id:
            raise ValueError("add patch object id mismatch")
        return self


class ScenePatch(StrictModel):
    scene_id: str
    base_scene_version: int = Field(ge=0)
    operations: list[ScenePatchOperation] = Field(min_length=1)


class SceneSnapshot(StrictModel):
    scene_id: str
    scene_version: int
    accepted: bool = True


class ModelProperty(StrictModel):
    asset_id: str
    semantic_name: str
    category: str
    dimensions_m: tuple[float, float, float]
    aabb_m: tuple[float, float, float, float, float, float] | None = None

    @model_validator(mode="after")
    def positive_dimensions(self):
        if any(value <= 0 for value in self.dimensions_m):
            raise ValueError("dimensions_m must be positive")
        return self

