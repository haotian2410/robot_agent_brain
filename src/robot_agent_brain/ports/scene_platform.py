from typing import Protocol
from ..contracts.camera import CameraFrame, CameraRequest
from ..contracts.scene import SceneConfig, ScenePatch, SceneSnapshot


class ScenePlatformPort(Protocol):
    def load_scene(self, scene: SceneConfig) -> SceneSnapshot: ...
    def apply_patch(self, patch: ScenePatch) -> SceneSnapshot: ...
    def capture(self, request: CameraRequest) -> CameraFrame: ...

