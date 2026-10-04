from __future__ import annotations
from copy import deepcopy

from ..contracts.camera import CameraRequest
from ..contracts.scene import SceneConfig, ScenePatch
from ..pipeline import BrainPipeline, BrainResult
from ..scene.scene_manager import SceneManager
from ..ports.scene_platform import ScenePlatformPort


class BrainSession:
    """Multi-turn semantic session; physical execution remains outside it."""

    def __init__(self, scene: SceneConfig, pipeline: BrainPipeline, platform: ScenePlatformPort):
        self.scene_manager = SceneManager(scene)
        self.scene = self.scene_manager.scene.model_copy(deep=True)
        self.pipeline = pipeline
        self.platform = platform
        self.platform.load_scene(self.scene)

    def apply_scene_patch(self, patch: ScenePatch) -> SceneConfig:
        candidate = deepcopy(self.scene_manager)
        candidate_scene = candidate.apply_patch(patch)
        snapshot = self.platform.apply_patch(patch)
        if snapshot.scene_id != candidate_scene.scene_id or snapshot.scene_version != candidate_scene.scene_version:
            raise ValueError("scene_platform_snapshot_mismatch")
        if not snapshot.accepted:
            raise ValueError(snapshot.error or "scene_platform_rejected_patch")
        self.scene_manager = candidate
        self.scene = candidate_scene
        return self.scene.model_copy(deep=True)

    def capture(self, request: CameraRequest | None = None):
        return self.platform.capture(request or CameraRequest())

    def run_task(self, request_id: str, instruction: str) -> BrainResult:
        return self.pipeline.run_turn(request_id, instruction, self.scene)
