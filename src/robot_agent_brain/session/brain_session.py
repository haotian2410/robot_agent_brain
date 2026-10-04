from __future__ import annotations

from ..contracts.camera import CameraRequest
from ..contracts.scene import SceneConfig, ScenePatch
from ..pipeline import BrainPipeline, BrainResult
from ..ports.scene_platform import ScenePlatformPort


class BrainSession:
    """Multi-turn semantic session; physical execution remains outside it."""

    def __init__(self, scene: SceneConfig, pipeline: BrainPipeline, platform: ScenePlatformPort):
        self.scene = scene.model_copy(deep=True)
        self.pipeline = pipeline
        self.platform = platform
        self.platform.load_scene(self.scene)

    def apply_scene_patch(self, patch: ScenePatch) -> SceneConfig:
        self.platform.apply_patch(patch)
        if getattr(self.platform, "manager", None) is not None:
            self.scene = self.platform.manager.scene.model_copy(deep=True)
        else:
            self.scene = self.scene.model_copy(update={"scene_version": self.scene.scene_version + 1})
        return self.scene.model_copy(deep=True)

    def capture(self, request: CameraRequest | None = None):
        return self.platform.capture(request or CameraRequest())

    def run_task(self, request_id: str, instruction: str) -> BrainResult:
        return self.pipeline.run(request_id, instruction, self.scene)

