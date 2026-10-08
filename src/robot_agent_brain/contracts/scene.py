"""Canonical team component Scene v1; no legacy flat runtime representation."""
import math
from typing import Annotated, Literal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


SceneId = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TransformProperties(StrictModel):
    position: tuple[float, float, float]
    quaternion_xyzw: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    parent: SceneId | None

    @model_validator(mode="after")
    def valid_transform(self):
        if not math.isclose(sum(v * v for v in self.quaternion_xyzw), 1, rel_tol=0, abs_tol=1e-6):
            raise ValueError("transform_quaternion_not_normalized")
        if any(v <= 0 for v in self.scale):
            raise ValueError("transform_scale_not_positive")
        return self


class MetadataRefProperties(StrictModel):
    # The team fixture uses <id> for illustration. Structural load must keep it
    # unchanged; only the asset adapter decides whether it can be resolved.
    path: str = Field(min_length=1)


class SemanticProperties(StrictModel):
    semantic_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    support: SceneId | None


class MeshRendererProperties(StrictModel):
    forceOverrideColor: str = Field(pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class LightProperties(StrictModel):
    type: str = Field(min_length=1)
    intensity: float = Field(ge=0)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class CameraProperties(StrictModel):
    type: str = Field(min_length=1)
    fov: float = Field(gt=0, lt=180)
    near: float = Field(gt=0)
    far: float = Field(gt=0)
    resolution: tuple[Annotated[int, Field(strict=True, gt=0)], Annotated[int, Field(strict=True, gt=0)]]

    @model_validator(mode="after")
    def valid_clipping(self):
        if self.far <= self.near:
            raise ValueError("camera_far_must_exceed_near")
        return self


class RobotDriverProperties(StrictModel):
    joint_sequence: list[str] = Field(min_length=1)
    joint_limits: dict[str, tuple[float, float]]

    @model_validator(mode="after")
    def valid_joints(self):
        if len(set(self.joint_sequence)) != len(self.joint_sequence) or any(not s for s in self.joint_sequence):
            raise ValueError("robot_joint_sequence_invalid")
        if set(self.joint_sequence) != set(self.joint_limits):
            raise ValueError("robot_joint_limits_coverage_invalid")
        if any(low > high for low, high in self.joint_limits.values()):
            raise ValueError("robot_joint_limits_invalid")
        return self


COMPONENT_PROPERTIES = {
    "Transform": TransformProperties, "MetadataRef": MetadataRefProperties,
    "Semantic": SemanticProperties, "MeshRenderer": MeshRendererProperties,
    "Light": LightProperties, "Camera": CameraProperties, "RobotDriver": RobotDriverProperties,
}


class SceneComponent(StrictModel):
    component_type: str = Field(min_length=1)
    properties: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_properties(self):
        def finite_json(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("scene_json_nonfinite")
            if isinstance(value, dict):
                for item in value.values():
                    finite_json(item)
            elif isinstance(value, list):
                for item in value:
                    finite_json(item)
        finite_json(self.properties)
        if self.component_type in COMPONENT_PROPERTIES:
            COMPONENT_PROPERTIES[self.component_type].model_validate(self.properties)
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema["allOf"] = [{
            "if": {"properties": {"component_type": {"const": name}}},
            "then": {"properties": {"properties": model.model_json_schema()}},
        } for name, model in COMPONENT_PROPERTIES.items()]
        return schema


class SceneObject(StrictModel):
    object_id_in_scene: SceneId
    object_name_in_scene: str
    components: list[SceneComponent]

    @model_validator(mode="after")
    def valid_components(self):
        names = [c.component_type for c in self.components]
        if names.count("Transform") != 1:
            raise ValueError("scene_requires_one_transform")
        if len(names) != len(set(names)):
            raise ValueError("scene_component_duplicate")
        return self


class SceneConfig(StrictModel):
    scene_schema_version: Literal[1]
    scene_version: Annotated[int, Field(strict=True, ge=0)]
    scene_id: SceneId
    scene_name: str
    objects: list[SceneObject]

    @field_validator("scene_schema_version", mode="before")
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("scene_schema_unsupported")
        return value

    @model_validator(mode="after")
    def validate_graph(self):
        ids = {obj.object_id_in_scene for obj in self.objects}
        if len(ids) != len(self.objects):
            raise ValueError("scene_object_id_duplicate")
        parents = {}
        for obj in self.objects:
            transform = next(c for c in obj.components if c.component_type == "Transform")
            parent = transform.properties["parent"]
            if parent is not None and (parent not in ids or parent == obj.object_id_in_scene):
                raise ValueError("scene_parent_invalid")
            parents[obj.object_id_in_scene] = parent
            semantic = next((c for c in obj.components if c.component_type == "Semantic"), None)
            if semantic is not None:
                support = semantic.properties["support"]
                if support is not None and (support not in ids or support == obj.object_id_in_scene):
                    raise ValueError("scene_support_invalid")
        completed = set()
        for identifier in ids:
            current, visited = identifier, set()
            while current is not None and current not in completed:
                if current in visited:
                    raise ValueError("scene_parent_cycle")
                visited.add(current)
                current = parents[current]
            completed.update(visited)
        return self


class PatchAction(StrEnum):
    ADD = "add_object"
    REMOVE = "remove_object"
    UPSERT_COMPONENT = "upsert_component"
    REMOVE_COMPONENT = "remove_component"


class ScenePatchOperation(StrictModel):
    action: PatchAction
    object_id_in_scene: SceneId
    object: SceneObject | None = None
    component: SceneComponent | None = None
    component_type: str | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        payload = {PatchAction.ADD: "object", PatchAction.REMOVE: None,
                   PatchAction.UPSERT_COMPONENT: "component", PatchAction.REMOVE_COMPONENT: "component_type"}[self.action]
        for field in ("object", "component", "component_type"):
            if (getattr(self, field) is not None) != (field == payload):
                raise ValueError("scene_patch_payload_mismatch")
        if self.object is not None and self.object.object_id_in_scene != self.object_id_in_scene:
            raise ValueError("scene_patch_object_id_mismatch")
        if self.component_type is not None and not self.component_type:
            raise ValueError("scene_patch_component_type_empty")
        return self


class ScenePatch(StrictModel):
    scene_id: SceneId
    base_scene_version: Annotated[int, Field(strict=True, ge=0)]
    operations: list[ScenePatchOperation] = Field(min_length=1)


class SceneSnapshot(StrictModel):
    scene_id: SceneId
    scene_version: Annotated[int, Field(strict=True, ge=0)]
    accepted: bool = True
    error: str | None = None


# Python spelling only: both names describe the exact component properties.
Transform = TransformProperties
