"""Explicit component reference remapping. Never guess that an integer is an ID."""
from dataclasses import dataclass
from pydantic import TypeAdapter

from ..contracts.scene import SceneConfig, SceneId, COMPONENT_PROPERTIES
from ..contracts.robot_setup import RobotSetup


@dataclass(frozen=True)
class RemappedScene:
    scene: SceneConfig
    id_map: dict[int, int]
    robot_setup: RobotSetup | None
    next_scene_object_id: int


def remap_scene(scene, *, new_scene_id, next_object_id, robot_setup=None):
    """Allocate every restored object above the session allocator high-water mark."""
    scene = SceneConfig.model_validate(scene.model_dump())
    TypeAdapter(SceneId).validate_python(new_scene_id)
    if new_scene_id == scene.scene_id:
        raise ValueError("scene_remap_requires_new_scene_id")
    if type(next_object_id) is not int or next_object_id < 0:
        raise ValueError("scene_remap_allocator_invalid")
    if next_object_id + len(scene.objects) > 2**53:
        raise ValueError("scene_object_id_exhausted")
    mapping = {obj.object_id_in_scene: next_object_id + i for i, obj in enumerate(scene.objects)}
    payload = scene.model_dump(mode="json")
    payload.update(scene_id=new_scene_id, scene_version=1)
    for obj in payload["objects"]:
        obj["object_id_in_scene"] = mapping[obj["object_id_in_scene"]]
        for component in obj["components"]:
            kind = component["component_type"]
            if kind not in COMPONENT_PROPERTIES:
                raise ValueError("scene_component_remap_rule_missing: " + kind)
            props = component["properties"]
            field = {"Transform": "parent", "Semantic": "support", "RobotAttachment": "parent_object_id"}.get(kind)
            if field is not None and props.get(field) is not None:
                try:
                    props[field] = mapping[props[field]]
                except KeyError as exc:
                    raise ValueError("scene_remap_reference_missing") from exc
    setup = None
    if robot_setup is not None:
        values = robot_setup.model_dump()
        for arm in values["arms"].values():
            if arm["robot_object_id"] not in mapping:
                raise ValueError("scene_remap_robot_missing")
            arm["robot_object_id"] = mapping[arm["robot_object_id"]]
        setup = RobotSetup.model_validate(values)
    return RemappedScene(SceneConfig.model_validate(payload), mapping, setup, next_object_id + len(scene.objects))
