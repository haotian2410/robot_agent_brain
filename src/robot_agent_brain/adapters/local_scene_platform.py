from ..contracts.scene import SceneSnapshot
from ..scene.scene_manager import SceneManager


class LocalScenePlatform:
    """Confirmed in-process metadata only; no rendering or robot execution."""
    def __init__(self):
        self.manager = None

    def load_scene(self, scene):
        candidate = SceneManager(scene)
        self.manager = candidate
        return SceneSnapshot(scene_id=candidate.scene.scene_id, scene_version=candidate.scene.scene_version)

    def apply_patch(self, patch):
        if self.manager is None:
            raise ValueError("scene_platform_not_loaded")
        scene = self.manager.apply_patch(patch)
        return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version)

    def capture(self, request):
        raise ValueError("vision_unavailable: local metadata platform does not render images")
