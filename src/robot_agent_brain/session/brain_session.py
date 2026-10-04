from ..contracts.camera import CameraRequest
from ..scene.scene_manager import SceneManager
from .dialogue_state import DialogueState

class BrainSession:
    """Local semantic state commits only after platform acknowledgement."""
    def __init__(self, scene, pipeline, platform):
        self.scene_manager = SceneManager(scene)
        self.pipeline, self.platform = pipeline, platform
        self.dialogue = DialogueState()
        self.session_action = None
        self._check_snapshot(platform.load_scene(self.scene), self.scene)

    @property
    def scene(self):
        return self.scene_manager.scene.model_copy(deep=True)

    @staticmethod
    def _check_snapshot(snapshot, expected):
        if not snapshot.accepted:
            raise ValueError(snapshot.error or "scene_platform_rejected_patch")
        if (snapshot.scene_id, snapshot.scene_version) != (expected.scene_id, expected.scene_version):
            raise ValueError("scene_platform_snapshot_mismatch")

    def apply_scene_patch(self, patch):
        candidate = SceneManager(self.scene)
        candidate_scene = candidate.apply_patch(patch)
        snapshot = self.platform.apply_patch(patch)
        self._check_snapshot(snapshot, candidate_scene)
        self.scene_manager = candidate
        return self.scene

    def capture(self, request=None):
        frame = self.platform.capture(request or CameraRequest())
        if (frame.scene_id, frame.scene_version) != (self.scene.scene_id, self.scene.scene_version):
            raise ValueError("camera_frame_scene_mismatch")
        return frame

    def run_task(self, request_id, instruction):
        if self.session_action == "close":
            raise ValueError("session_closed")
        result = self.pipeline.run(request_id, instruction, self.scene,
                                   dialogue=self.dialogue, capture=self.capture)
        if result.scene_patch is not None:
            self.apply_scene_patch(result.scene_patch)
        if result.session_action is not None:
            self.session_action = result.session_action.action
        self.dialogue.observe(result)
        return result
