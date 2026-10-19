"""Canonical team component Scene v1; no legacy flat runtime representation."""
import math
from typing import Annotated, Literal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


SceneId = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TransformProperties(StrictModel):
    position: tuple[float, float, float] | None = None
    quaternion_xyzw: tuple[float, float, float, float] | None = None
    scale: tuple[float, float, float]
    parent: SceneId | None

    @model_validator(mode="after")
    def valid_transform(self):
        if (self.position is None) != (self.quaternion_xyzw is None):
            raise ValueError("transform_pose_fields_must_be_present_together")
        if self.quaternion_xyzw is not None:
            norm = sum(v * v for v in self.quaternion_xyzw)
            if not math.isfinite(norm) or not math.isclose(norm, 1, rel_tol=0, abs_tol=1e-4):
                raise ValueError("transform_quaternion_not_normalized")
        if any(v <= 0 for v in self.scale):
            raise ValueError("transform_scale_not_positive")
        return self


class MetadataRefProperties(StrictModel):
    # The team fixture uses <id> for illustration. Structural load must keep it
    # unchanged; only the asset adapter decides whether it can be resolved.
    path: str = Field(min_length=1)
    type: Literal["model", "robot"] | None = None


class SemanticProperties(StrictModel):
    semantic_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    support: SceneId | None


class MeshRendererProperties(StrictModel):
    forceOverrideColor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


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
    joint_limits: dict[str, tuple[float, float]] | None = None
    initial_joint_positions_rad: dict[str, float] | None = None
    now_joint_positions_rad: dict[str, float] | None = None
    available_connect_joints: list[str] | None = None

    @model_validator(mode="after")
    def valid_joints(self):
        if len(set(self.joint_sequence)) != len(self.joint_sequence) or any(not s for s in self.joint_sequence):
            raise ValueError("robot_joint_sequence_invalid")
        if self.joint_limits and set(self.joint_sequence) != set(self.joint_limits):
            raise ValueError("robot_joint_limits_coverage_invalid")
        if self.joint_limits is None and self.available_connect_joints is None:
            raise ValueError("robot_joint_limits_missing")
        if any(low > high for low, high in (self.joint_limits or {}).values()):
            raise ValueError("robot_joint_limits_invalid")
        if self.initial_joint_positions_rad is not None and not set(self.initial_joint_positions_rad) <= set(self.joint_sequence):
            raise ValueError("robot_initial_joint_invalid")
        if self.now_joint_positions_rad is not None and not set(self.now_joint_positions_rad) <= set(self.joint_sequence):
            raise ValueError("robot_current_joint_invalid")
        # Fixed mounting joints need not be actuated. Asset-aware validation
        # checks these names against the complete URDF inventory offline.
        if self.available_connect_joints is not None and (len(set(self.available_connect_joints)) != len(self.available_connect_joints)
                or any(not name for name in self.available_connect_joints)):
            raise ValueError("robot_connect_joint_invalid")
        return self

    def deployment_configuration(self):
        return self.model_dump(exclude={"now_joint_positions_rad"})


class RobotAttachmentProperties(StrictModel):
    parent_object_id: SceneId
    parent_joint: str = Field(min_length=1)
    parent_link: str = Field(min_length=1)
    child_link: str = Field(min_length=1)
    connection_type: Literal["fixed"]
    transform: dict[str, list[float] | str]

    @model_validator(mode="after")
    def valid_attachment_transform(self):
        required = {"position", "quaternion_xyzw", "reference_frame"}
        if set(self.transform) != required:
            raise ValueError("robot_attachment_transform_invalid")
        position = self.transform["position"]
        quaternion = self.transform["quaternion_xyzw"]
        if not isinstance(position, list) or len(position) != 3 or not isinstance(quaternion, list) or len(quaternion) != 4:
            raise ValueError("robot_attachment_transform_invalid")
        if not all(math.isfinite(v) for v in [*position, *quaternion]):
            raise ValueError("robot_attachment_transform_invalid")
        norm = sum(float(value) ** 2 for value in quaternion)
        if not math.isfinite(norm) or not math.isclose(norm, 1, rel_tol=0, abs_tol=.04):
            raise ValueError("robot_attachment_quaternion_not_normalized")
        if not isinstance(self.transform["reference_frame"], str) or not self.transform["reference_frame"]:
            raise ValueError("robot_attachment_reference_frame_invalid")
        return self


COMPONENT_PROPERTIES = {
    "Transform": TransformProperties, "MetadataRef": MetadataRefProperties,
    "Semantic": SemanticProperties, "MeshRenderer": MeshRendererProperties,
    "Light": LightProperties, "Camera": CameraProperties, "RobotDriver": RobotDriverProperties,
    "RobotAttachment": RobotAttachmentProperties,
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
        transform = next(c for c in self.components if c.component_type == "Transform")
        attachment = next((c for c in self.components if c.component_type == "RobotAttachment"), None)
        if attachment is not None:
            parent = attachment.properties["parent_object_id"]
            if transform.properties["parent"] != parent:
                raise ValueError("robot_attachment_parent_mismatch")
            if transform.properties.get("position") is not None or transform.properties.get("quaternion_xyzw") is not None:
                raise ValueError("robot_attachment_transform_must_omit_pose")
        elif transform.properties.get("position") is None:
            raise ValueError("transform_pose_required_without_attachment")
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
