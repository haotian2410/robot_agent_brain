from ..contracts.camera import CameraRequest
from ..contracts.commands import ExecutionFeedback
from ..scene.scene_manager import SceneManager
from .dialogue_state import DialogueState

class BrainSession:
    """Local semantic state commits only after platform acknowledgement."""
    def __init__(self, scene, pipeline, platform):
        self.scene_manager = SceneManager(scene)
        self.pipeline, self.platform = pipeline, platform
        self.dialogue = DialogueState()
        self.session_action = None
        self.sync_state = "synchronized"
        self.holding_object = None
        self.last_request_id = None
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
        try:
            snapshot = self.platform.apply_patch(patch)
        except Exception:
            self.sync_state = "unknown"
            raise
        try:
            self._check_snapshot(snapshot, candidate_scene)
        except Exception:
            self.sync_state = "unknown"
            raise
        self.sync_state = "synchronized"
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
        if self.session_action == "pause" and not any(token in instruction.casefold() for token in ("resume", "继续", "恢复")):
            raise ValueError("session_paused")
        if self.sync_state != "synchronized":
            raise ValueError("scene_sync_unknown")
        result = self.pipeline.run(request_id, instruction, self.scene,
                                   dialogue=self.dialogue, capture=self.capture, held_object=self.holding_object)
        self.last_request_id = request_id
        if result.scene_patch is not None:
            self.apply_scene_patch(result.scene_patch)
        if result.session_action is not None:
            self.session_action = result.session_action.action
        self.dialogue.observe(result)
        return result

    def apply_execution_feedback(self, feedback: ExecutionFeedback):
        if self.last_request_id != feedback.request_id:
            raise ValueError("execution_feedback_stale_or_unknown_request")
        self.holding_object = feedback.holding_object
        return feedback.status
