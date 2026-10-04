from __future__ import annotations

from ..contracts.camera import CameraFrame, CameraRequest
from ..contracts.scene import SceneConfig, ScenePatch, SceneSnapshot
from ..scene.scene_manager import SceneManager


class MockScenePlatform:
    """In-memory scene platform used by tests and non-physical integration."""

    def __init__(self, rgb: bytes = b"mock-rgb"):
        self.manager: SceneManager | None = None
        self.rgb = rgb

    def load_scene(self, scene: SceneConfig) -> SceneSnapshot:
        self.manager = SceneManager(scene)
        return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version)

    def apply_patch(self, patch: ScenePatch) -> SceneSnapshot:
        if self.manager is None:
            raise RuntimeError("scene_platform_not_loaded")
        scene = self.manager.apply_patch(patch)
        return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version)

    def capture(self, request: CameraRequest) -> CameraFrame:
        if self.manager is None:
            raise RuntimeError("scene_platform_not_loaded")
        scene = self.manager.scene
        return CameraFrame(
            camera_id=request.camera_id,
            scene_id=scene.scene_id,
            scene_version=scene.scene_version,
            width=request.width,
            height=request.height,
            rgb=self.rgb,
        )

