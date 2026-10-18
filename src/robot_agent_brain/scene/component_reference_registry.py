"""Explicit deployment rules for object references; integers are never guessed."""
from copy import deepcopy
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from ..contracts.scene import COMPONENT_PROPERTIES, SceneConfig, SceneId


class ReferenceField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: list[str] = Field(min_length=1)
    shape: Literal["single", "list", "map_values"] = "single"
    nullable: bool = False
    optional: bool = False
    target_type: Literal["any", "model", "robot"] = "any"


class ComponentReferenceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    no_object_references: bool = False
    references: list[ReferenceField] = Field(default_factory=list)

    @model_validator(mode="after")
    def unambiguous(self):
        if self.no_object_references == bool(self.references):
            raise ValueError("component_reference_rule_ambiguous")
        paths = [tuple(r.path) for r in self.references]
        if any(a == b[:len(a)] for i, a in enumerate(paths) for j, b in enumerate(paths) if i != j):
            raise ValueError("component_reference_paths_overlap")
        return self


class ComponentReferenceRegistry:
    def __init__(self, rules=None):
        self.rules = {name: ComponentReferenceRule(no_object_references=True) for name in COMPONENT_PROPERTIES}
        for name, field in (("Transform", "parent"), ("Semantic", "support"), ("RobotAttachment", "parent_object_id")):
            self.rules[name] = ComponentReferenceRule(references=[ReferenceField(path=[field], nullable=True, optional=True)])
        for name, rule in (rules or {}).items():
            if name in self.rules:
                raise ValueError("component_reference_builtin_override_forbidden")
            self.rules[name] = ComponentReferenceRule.model_validate(rule)

    def _slots(self, component):
        kind = component["component_type"]
        if kind not in self.rules:
            raise ValueError("scene_component_remap_rule_missing: " + kind)
        props = component["properties"]
        json.dumps(props, allow_nan=False)
        for field in self.rules[kind].references:
            parent = props
            for key in field.path[:-1]:
                if not isinstance(parent, dict) or key not in parent:
                    if field.optional:
                        parent = None
                        break
                    raise ValueError("scene_reference_path_missing")
                parent = parent[key]
            if parent is None and field.optional:
                continue
            key = field.path[-1]
            if not isinstance(parent, dict) or key not in parent:
                if field.optional:
                    continue
                raise ValueError("scene_reference_path_missing")
            value = parent[key]
            if field.shape == "single":
                slots = [(parent, key)]
            elif field.shape == "list" and isinstance(value, list):
                slots = [(value, i) for i in range(len(value))]
            elif field.shape == "map_values" and isinstance(value, dict):
                slots = [(value, k) for k in value]
            else:
                raise ValueError("scene_reference_shape_invalid")
            for container, slot in slots:
                identifier = container[slot]
                if identifier is None and field.nullable:
                    continue
                TypeAdapter(SceneId).validate_python(identifier)
                yield container, slot, field

    def references(self, component):
        data = component.model_dump(mode="json") if hasattr(component, "model_dump") else component
        return [container[key] for container, key, _ in self._slots(data)]

    def remap_component(self, component, mapping):
        data = deepcopy(component)
        for container, key, _ in self._slots(data):
            if container[key] not in mapping:
                raise ValueError("scene_remap_reference_missing")
            container[key] = mapping[container[key]]
        return data

    def validate_scene(self, scene):
        from .component_access import SceneIndex
        scene = SceneConfig.model_validate(scene.model_dump())
        known = {o.object_id_in_scene for o in scene.objects}
        index = SceneIndex(scene)
        for obj in scene.objects:
            for component in obj.components:
                for container, key, field in self._slots(component.model_dump(mode="json")):
                    identifier = container[key]
                    if identifier not in known:
                        raise ValueError("scene_remap_reference_missing")
                    if field.target_type != "any" and index.metadata_type(identifier) != field.target_type:
                        raise ValueError("scene_reference_target_type_invalid")
        return scene
