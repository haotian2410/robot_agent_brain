"""Canonical team component Scene v1; no legacy flat runtime representation."""
import copy
import math
from dataclasses import dataclass
from typing import Annotated, Literal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PrivateAttr, field_validator, model_validator


SceneId = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TransformProperties(StrictModel):
    position: tuple[float, float, float] | None = (0.0, 0.0, 0.0)
    quaternion_xyzw: tuple[float, float, float, float] | None = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    parent: SceneId | None = None

    @model_validator(mode="after")
    def valid_transform(self):
        if self.position is None:
            self.position = (0.0, 0.0, 0.0)
        if self.quaternion_xyzw is None:
            self.quaternion_xyzw = (0.0, 0.0, 0.0, 1.0)
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
    path: str | None = None
    type: str | None = None


class SemanticProperties(StrictModel):
    semantic_name: str = ""
    category: str = ""
    support: SceneId | None = None


class MeshRendererProperties(StrictModel):
    forceOverrideColor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class LightProperties(StrictModel):
    type: str = "Ambient"
    intensity: float = 1.0
    color: str = "#FFFFFF"


class CameraProperties(StrictModel):
    type: str = "rgb"
    fov: float = 60.0
    near: float = 0.1
    far: float = 1000.0
    resolution: tuple[Annotated[int, Field(strict=True, gt=0)], Annotated[int, Field(strict=True, gt=0)]] = (640, 480)

    @model_validator(mode="after")
    def valid_clipping(self):
        if self.far < self.near * 10:
            self.far = self.near * 10
        return self


class RobotDriverProperties(StrictModel):
    joint_sequence: list[str] = Field(default_factory=list)
    joint_limits: dict[str, tuple[float, float]] | None = None
    initial_joint_positions_rad: dict[str, float] | None = None
    now_joint_positions_rad: dict[str, float] | None = None
    available_connect_joints: list[str] | None = None
    role: str = "arm"

    @model_validator(mode="after")
    def valid_joints(self):
        if len(set(self.joint_sequence)) != len(self.joint_sequence) or any(not s for s in self.joint_sequence):
            raise ValueError("robot_joint_sequence_invalid")
        # A driven arm must declare limits.  End-effectors in the OLS scenes are the one
        # deliberate exception: they expose a fixed mounting joint and are validated against
        # the URDF inventory instead of carrying actuator limits in the scene document.
        if self.role != "passive" and self.joint_sequence and self.joint_limits is None and self.available_connect_joints is None:
            raise ValueError("robot_joint_limits_missing")
        if any(low > high for low, high in (self.joint_limits or {}).values()):
            raise ValueError("robot_joint_limits_invalid")
        if self.role != "passive":
            self.role = "arm"
        if self.role != "passive" and not self.joint_sequence:
            raise ValueError("robot_joint_sequence_invalid")
        # Fixed mounting joints need not be actuated. Asset-aware validation
        # checks these names against the complete URDF inventory offline.
        if self.available_connect_joints is not None and (len(set(self.available_connect_joints)) != len(self.available_connect_joints)
                or any(not name for name in self.available_connect_joints)):
            raise ValueError("robot_connect_joint_invalid")
        if self.now_joint_positions_rad is not None:
            if any(not isinstance(value, (int, float)) or not math.isfinite(float(value))
                   for value in self.now_joint_positions_rad.values()):
                raise ValueError("robot_now_joint_position_invalid")
            unknown = set(self.now_joint_positions_rad) - set(self.joint_sequence)
            if unknown:
                raise ValueError("robot_now_joint_unknown:" + ",".join(sorted(unknown)))
        return self

    def deployment_configuration(self):
        return self.model_dump(exclude={"now_joint_positions_rad"})


class RobotAttachmentProperties(StrictModel):
    parent_object_id: SceneId
    parent_joint: str = ""
    parent_link: str = ""
    child_link: str = ""
    connection_type: str = "fixed"
    transform: dict[str, list[float] | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_attachment_transform(self):
        position = self.transform.get("position")
        quaternion = self.transform.get("quaternion_xyzw")
        if position is None or quaternion is None:
            return self
        if not isinstance(position, list) or len(position) != 3 or not isinstance(quaternion, list) or len(quaternion) != 4:
            return self
        if not all(math.isfinite(v) for v in [*position, *quaternion]):
            raise ValueError("robot_attachment_transform_invalid")
        norm = sum(float(value) ** 2 for value in quaternion)
        if not math.isfinite(norm) or not math.isclose(norm, 1, rel_tol=0, abs_tol=.04):
            raise ValueError("robot_attachment_quaternion_not_normalized")
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
        return self


class SceneConfig(StrictModel):
    scene_schema_version: Literal[1]
    scene_version: Annotated[int, Field(strict=True, ge=0)] = 0
    scene_id: SceneId = 0
    scene_name: str = ""
    scene_sub_version: Annotated[int, Field(strict=True, ge=0)] = 0
    objects: list[SceneObject] = Field(default_factory=list)

    _raw_document: dict | None = PrivateAttr(default=None)
    _raw_has_sub_version: bool = PrivateAttr(default=False)
    _rejected_objects: list[dict] = PrivateAttr(default_factory=list)

    def raw_document(self):
        return copy.deepcopy(self._raw_document) if self._raw_document is not None else self.model_dump(mode="json")

    @field_validator("scene_schema_version", mode="before")
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("scene_schema_unsupported")
        return value

    @model_validator(mode="after")
    def track_document_fields(self):
        self._raw_has_sub_version = "scene_sub_version" in self.model_fields_set
        return self

    def model_dump(self, *args, **kwargs):
        value = super().model_dump(*args, **kwargs)
        if not self._raw_has_sub_version and value.get("scene_sub_version") == 0:
            value.pop("scene_sub_version", None)
        return value

    def __eq__(self, other):
        if isinstance(other, SceneConfig):
            left = self.model_dump(mode="json")
            right = other.model_dump(mode="json")
            # Typed-view equality treats an omitted optional sub-version and
            # an explicit zero as the same view.  Document digests still
            # distinguish the two raw JSON documents.
            if left.get("scene_sub_version") == 0:
                left.pop("scene_sub_version", None)
            if right.get("scene_sub_version") == 0:
                right.pop("scene_sub_version", None)
            return left == right
        return NotImplemented

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


@dataclass(frozen=True)
class SceneDocument:
    """Lossless wire document plus a permissive typed view.

    The raw mapping is the only source for protocol digests and round-trips.
    ``view`` is deliberately a separate, normalized representation used by
    Brain's existing scene algorithms.
    """

    raw: dict
    view: SceneConfig
    rejected_objects: list[dict]
    warnings: list[str]


def parse_scene_document(value, *, uint32=True):
    """Parse a WebEditor Scene v1 document without rewriting its raw JSON."""
    if not isinstance(value, dict):
        raise ValueError("scene_file_invalid")
    if type(value.get("scene_schema_version")) is not int or value.get("scene_schema_version") != 1:
        raise ValueError("scene_schema_unsupported")
    raw = copy.deepcopy(value)
    objects_raw = raw.get("objects", [])
    if not isinstance(objects_raw, list):
        objects_raw = []
    limit = 2**32 if uint32 else 2**53
    rejected, warnings, accepted = [], [], []
    id_to_index, id_to_obj = {}, {}
    for index, item in enumerate(objects_raw):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "object_invalid"})
            continue
        identifier = item.get("object_id_in_scene")
        if type(identifier) is not int or not 0 <= identifier < limit or identifier in id_to_obj:
            rejected.append({"index": index, "reason": "object_id_invalid"})
            continue
        id_to_index[identifier] = index
        id_to_obj[identifier] = item
    def components_for(item):
        values = item.get("components", [])
        if not isinstance(values, list):
            warnings.append("components_not_array")
            values = []
        seen, components = set(), []
        for component in values:
            if not isinstance(component, dict) or not isinstance(component.get("component_type"), str):
                warnings.append("component_invalid")
                continue
            name = component["component_type"]
            if name in seen:
                warnings.append(f"component_duplicate:{name}")
                continue
            seen.add(name)
            properties = component.get("properties", {})
            components.append({"component_type": name, "properties": copy.deepcopy(properties) if isinstance(properties, dict) else {}})
        if "Transform" not in seen:
            warnings.append("transform_missing")
            components.append({"component_type": "Transform", "properties": {
                "position": [0.0, 0.0, 0.0], "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scale": [1.0, 1.0, 1.0], "parent": None}})
        return components
    normalized = {}
    for identifier, item in id_to_obj.items():
        components = components_for(item)
        transform = next(c["properties"] for c in components if c["component_type"] == "Transform")
        parent = transform.get("parent")
        if parent == 0xFFFFFFFF:
            parent = None
        if type(parent) is not int or not 0 <= parent < limit:
            parent = None if parent is None else "__invalid__"
        normalized[identifier] = {
            "object_id_in_scene": identifier,
            "object_name_in_scene": item.get("object_name_in_scene") if isinstance(item.get("object_name_in_scene"), str)
                else f"object_{identifier}",
            "components": components,
            "_parent": parent,
        }
    invalid_ids = set()
    for identifier, item in normalized.items():
        parent = item["_parent"]
        if parent == "__invalid__" or (parent is not None and parent not in normalized):
            invalid_ids.add(identifier)
    for identifier in list(normalized):
        visited, current = set(), identifier
        while current is not None and current in normalized and current not in invalid_ids:
            if current in visited:
                invalid_ids.update(visited)
                break
            visited.add(current)
            current = normalized[current]["_parent"]
    def descendants(identifier):
        result = {identifier}
        changed = True
        while changed:
            changed = False
            for child, item in normalized.items():
                if child not in result and item["_parent"] in result:
                    result.add(child); changed = True
        return result
    for identifier in list(invalid_ids):
        invalid_ids.update(descendants(identifier))
    for identifier in sorted(invalid_ids):
        rejected.append({"index": id_to_index[identifier], "object_id_in_scene": identifier, "reason": "parent_invalid"})
    for identifier, item in normalized.items():
        if identifier in invalid_ids:
            continue
        components = [SceneComponent.model_construct(component_type=c["component_type"], properties=c["properties"])
                      for c in item["components"]]
        accepted.append(SceneObject.model_construct(object_id_in_scene=identifier,
            object_name_in_scene=item["object_name_in_scene"], components=components))
    scene = SceneConfig.model_construct(
        scene_schema_version=1,
        scene_version=value.get("scene_version") if type(value.get("scene_version")) is int and value.get("scene_version") >= 0 else 0,
        scene_id=value.get("scene_id") if type(value.get("scene_id")) is int and 0 <= value.get("scene_id") < limit else 0,
        scene_name=value.get("scene_name") if isinstance(value.get("scene_name"), str) else "",
        scene_sub_version=value.get("scene_sub_version") if type(value.get("scene_sub_version")) is int and 0 <= value.get("scene_sub_version") < limit else 0,
        objects=accepted)
    scene._raw_document = raw
    scene._raw_has_sub_version = "scene_sub_version" in raw
    return SceneDocument(raw=raw, view=scene, rejected_objects=rejected, warnings=warnings)

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
    scene_sub_version: Annotated[int, Field(strict=True, ge=0)] = 0
    accepted: bool = True
    error: str | None = None


# Python spelling only: both names describe the exact component properties.
Transform = TransformProperties
