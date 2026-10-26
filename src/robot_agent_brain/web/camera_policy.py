"""Explicit overhead semantics, never array order or guessed attachment pose."""
from ..scene.component_access import SceneIndex


def choose_camera(scene, *, semantic_names=("overhead_camera_d435i", "overhead_camera", "top_camera")):
    if scene is None:
        return None, "scene_not_available"
    index = SceneIndex(scene)
    cameras = [o for o in scene.objects if index.component(o.object_id_in_scene, "Camera")]
    overhead = [o for o in cameras if index.semantic(o.object_id_in_scene)
                and index.semantic(o.object_id_in_scene).semantic_name.casefold() in semantic_names]
    if len(overhead) == 1:
        return overhead[0].object_id_in_scene, "explicit_overhead_semantic"
    if len(cameras) == 1:
        return cameras[0].object_id_in_scene, "only_camera"
    return None, "camera_selection_requires_clarification" if cameras else "no_camera"
