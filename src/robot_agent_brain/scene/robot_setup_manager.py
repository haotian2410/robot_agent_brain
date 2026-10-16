"""Prepare robot-only scene replacement without mutating the live session."""
from dataclasses import dataclass
from pydantic import TypeAdapter

from ..contracts.scene import SceneConfig, SceneId, COMPONENT_PROPERTIES
from ..contracts.robot_setup import RobotSetup
from .component_access import SceneIndex


@dataclass(frozen=True)
class PreparedRobotSetup:
    scene: SceneConfig
    setup: RobotSetup
    robot_object_ids: set[int]
    platform_object_ids: set[int]
    template_id_map: dict[int, int]


class RobotSetupManager:
    def prepare(self, scene, *, current_robot_ids, target_profile, platform_bindings, next_object_id):
        """platform_bindings explicitly maps target template anchors to live IDs.

        Objects outside the robot manifest are not imported from the template.
        No name/pose-based matching and no implicit task-object reparenting.
        """
        scene = SceneConfig.model_validate(scene.model_dump())
        objects = {o.object_id_in_scene: o for o in scene.objects}
        removed = set(current_robot_ids)
        if not removed or not removed <= set(objects):
            raise ValueError("robot_setup_current_manifest_invalid")
        for identifier in removed:
            TypeAdapter(SceneId).validate_python(identifier)
        target = target_profile
        anchors = target.platform_object_ids - target.robot_object_ids
        if set(platform_bindings) != anchors or len(set(platform_bindings.values())) != len(platform_bindings):
            raise ValueError("robot_setup_platform_binding_invalid")
        if not set(platform_bindings.values()) <= set(objects) - removed:
            raise ValueError("robot_setup_platform_binding_invalid")
        for identifier in platform_bindings.values():
            TypeAdapter(SceneId).validate_python(identifier)
        if type(next_object_id) is not int or next_object_id <= max(objects, default=-1):
            raise ValueError("robot_setup_allocator_invalid")
        if next_object_id + len(target.robot_object_ids) > 2**53:
            raise ValueError("scene_object_id_exhausted")
        # Unknown components could contain references into the removed graph;
        # keep the live scene intact and ask for a remapping rule instead.
        for obj in scene.objects:
            if obj.object_id_in_scene in removed:
                continue
            for component in obj.components:
                if component.component_type not in COMPONENT_PROPERTIES:
                    raise ValueError("robot_setup_component_reference_rule_missing: " + component.component_type)
                field = {"Transform": "parent", "Semantic": "support", "RobotAttachment": "parent_object_id"}.get(component.component_type)
                if field and component.properties.get(field) in removed:
                    raise ValueError("robot_setup_task_depends_on_old_robot")
        mapping = dict(platform_bindings)
        mapping.update({identifier: next_object_id + i for i, identifier in enumerate(sorted(target.robot_object_ids))})
        additions = []
        for obj in target.template.objects:
            if obj.object_id_in_scene not in target.robot_object_ids:
                continue
            value = obj.model_dump(mode="json")
            value["object_id_in_scene"] = mapping[obj.object_id_in_scene]
            for component in value["components"]:
                kind = component["component_type"]
                if kind not in COMPONENT_PROPERTIES:
                    raise ValueError("scene_component_remap_rule_missing: " + kind)
                field = {"Transform": "parent", "Semantic": "support", "RobotAttachment": "parent_object_id"}.get(kind)
                if field is not None and component["properties"].get(field) is not None:
                    reference = component["properties"][field]
                    if reference not in mapping:
                        raise ValueError("robot_setup_template_reference_unbound")
                    component["properties"][field] = mapping[reference]
            additions.append(value)
        payload = scene.model_dump(mode="json")
        payload["objects"] = [o for o in payload["objects"] if o["object_id_in_scene"] not in removed] + additions
        payload["scene_version"] += 1
        candidate = SceneConfig.model_validate(payload)
        setup = target.setup.model_dump()
        for arm in setup["arms"].values():
            arm["robot_object_id"] = mapping[arm["robot_object_id"]]
        setup = RobotSetup.model_validate(setup)
        target.validate_scene(candidate, setup)
        return PreparedRobotSetup(candidate, setup, {mapping[i] for i in target.robot_object_ids},
                                  {mapping[i] for i in target.platform_object_ids}, mapping)
