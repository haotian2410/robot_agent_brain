from __future__ import annotations

from enum import StrEnum
import math
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transform(StrictModel):
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    quaternion_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @model_validator(mode="after")
    def valid_transform(self):
        if not all(math.isfinite(v) for v in (*self.position, *self.quaternion_xyzw, *self.scale)):
            raise ValueError("transform values must be finite")
        if not math.isclose(math.sqrt(sum(v*v for v in self.quaternion_xyzw)), 1.0, rel_tol=0, abs_tol=1e-6):
            raise ValueError("transform quaternion must be normalized (xyzw)")
        if any(value <= 0 for value in self.scale):
            raise ValueError("transform scale must be positive")
        return self


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
    retired_object_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_objects(self):
        ids = [item.scene_object_id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_object_id must be unique")
        if set(ids) & set(self.retired_object_ids):
            raise ValueError("active object id cannot be retired")
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
    error: str | None = None


class ModelProperty(StrictModel):
    asset_id: str
    semantic_name: str
    category: str
    dimensions_m: tuple[float, float, float]
    aabb_m: tuple[float, float, float, float, float, float] | None = None

    @model_validator(mode="after")
    def positive_dimensions(self):
        if any(not math.isfinite(value) or value <= 0 for value in self.dimensions_m):
            raise ValueError("dimensions_m must be positive")
        if any(not value.strip() for value in (self.asset_id, self.semantic_name, self.category)):
            raise ValueError("asset identifiers and names must not be empty")
        if self.aabb_m is not None:
            if not all(math.isfinite(v) for v in self.aabb_m) or any(self.aabb_m[i] >= self.aabb_m[i+3] for i in range(3)):
                raise ValueError("invalid asset AABB: expected min xyz then max xyz")
        return self
