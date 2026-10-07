from ..contracts.camera import CameraRequest
from ..contracts.commands import ExecutionFeedback, canonical_commands
from ..contracts.scene import SceneConfig
from ..scene.scene_manager import SceneManager
from .dialogue_state import DialogueState

class BrainSession:
    """Local semantic state commits only after platform acknowledgement."""
    def __init__(self, scene, pipeline, platform):
        self.scene_manager = None
        self.pipeline, self.platform = pipeline, platform
        self.dialogue = DialogueState()
        self.session_action = None
        self.sync_state = "synchronized"
        self.holding_object = None
        self.last_request_id = None
        self.last_exported_request = None
        self.exported_commands = {}
        self.dispatched_requests = set()
        self.pending_commands = None
        self.pending_execution_request = None
        if scene is not None:
            self.initialize_scene(scene)

    @property
    def scene(self):
        return self.scene_manager.scene.model_copy(deep=True) if self.scene_manager else None

    def require_scene(self):
        if self.scene is None:
            raise ValueError("scene_required")
        return self.scene

    def initialize_scene(self, scene):
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        candidate = SceneManager(scene)
        try:
            self._check_snapshot(self.platform.load_scene(candidate.scene), candidate.scene)
        except Exception:
            self.sync_state = "unknown"
            raise
        self.scene_manager = candidate
        self.sync_state = "synchronized"
        self.dialogue = DialogueState()
        self.holding_object = None
        self.exported_commands.clear()
        self.last_exported_request = None
        self.last_request_id = None

    @staticmethod
    def _check_snapshot(snapshot, expected):
        if not snapshot.accepted:
            raise ValueError(snapshot.error or "scene_platform_rejected_patch")
        if (snapshot.scene_id, snapshot.scene_version) != (expected.scene_id, expected.scene_version):
            raise ValueError("scene_platform_snapshot_mismatch")

    def apply_scene_patch(self, patch):
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        candidate = SceneManager(self.require_scene())
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
        self.require_scene()
        frame = self.platform.capture(request or CameraRequest())
        if (frame.scene_id, frame.scene_version) != (self.scene.scene_id, self.scene.scene_version):
            raise ValueError("camera_frame_scene_mismatch")
        return frame

    def run_task(self, request_id, instruction):
        if self.session_action == "close":
            raise ValueError("session_closed")
        turn = self.pipeline.understand_turn(instruction, scene=self.scene, dialogue=self.dialogue)
        return self.process_turn(request_id, turn)

    def check_turn(self, turn):
        if self.session_action == "close":
            raise ValueError("session_closed")
        if self.sync_state != "synchronized" and turn.turn_kind != "session_control":
            raise ValueError("scene_sync_unknown")
        if self.pending_execution_request is not None and turn.turn_kind != "session_control":
            raise ValueError("execution_pending")
        if self.session_action == "pause" and (turn.session_control is None or turn.session_control.action not in {"resume", "close"}):
            raise ValueError("session_paused")

    def process_turn(self, request_id, turn, *, bindings_override=None, edit_defaults=None):
        self.check_turn(turn)
        result = self.pipeline.process_turn(request_id, turn, self.scene,
                                           dialogue=self.dialogue, capture=self.capture,
                                           held_object=self.holding_object, bindings_override=bindings_override, edit_defaults=edit_defaults)
        return self._accept_result(request_id, result)

    def process_initial_robot_turn(self, request_id, turn, scene, *, bindings_override):
        """Plan against a prospective bootstrap; load it only after validation.

        Bootstrap supplies complete instance bindings, so this path needs no
        rendered vision fallback. Never load a scene for a failed planner.
        """
        self.check_turn(turn)
        if self.scene is not None or turn.turn_kind != "robot_task" or turn.status != "accepted":
            raise ValueError("initial_robot_turn_required")
        result = self.pipeline.process_turn(request_id, turn, scene, bindings_override=bindings_override)
        self.initialize_scene(scene)
        return self._accept_result(request_id, result)

    def _accept_result(self, request_id, result):
        if self.session_action == "pause":
            if result.session_action is None or result.session_action.action not in {"resume", "close"}:
                raise ValueError("session_paused")
        if result.commands is not None:
            if request_id in self.exported_commands or request_id in self.dispatched_requests:
                raise ValueError("request_id_reused")
            self.exported_commands[request_id] = canonical_commands(result.commands)
            self.last_exported_request = request_id
            self.last_request_id = request_id
        if result.scene_patch is not None:
            if self.holding_object and any(op.scene_object_id == self.holding_object for op in result.scene_patch.operations):
                raise ValueError("scene_edit_held_object_conflict")
            self.apply_scene_patch(result.scene_patch)
        if result.session_action is not None:
            self.session_action = result.session_action.action
        self.dialogue.observe(result)
        return result

    def mark_dispatched(self, commands):
        if self.pending_execution_request is not None:
            raise ValueError("execution_pending")
        if self.sync_state != "synchronized" or self.session_action in {"pause", "close"}:
            raise ValueError("session_not_ready_for_dispatch")
        scene = self.require_scene()
        if (commands.scene_id, commands.scene_version) != (scene.scene_id, scene.scene_version):
            raise ValueError("execution_scene_mismatch")
        payload = canonical_commands(commands)
        if commands.request_id in self.dispatched_requests or self.exported_commands.get(commands.request_id) != payload:
            raise ValueError("execution_not_exported_by_session")
        self.pending_commands = payload
        self.pending_execution_request = commands.request_id
        self.dispatched_requests.add(commands.request_id)

    def apply_execution_feedback(self, feedback: ExecutionFeedback, *, confirmed_scene=None, feedback_source="external"):
        feedback = ExecutionFeedback.model_validate(feedback.model_dump())
        if self.pending_execution_request != feedback.request_id:
            raise ValueError("execution_feedback_stale_or_unknown_request")
        expected = {c["command_id"] for c in self.pending_commands["commands"]}
        actual = [c.command_id for c in feedback.commands]
        if len(actual) != len(set(actual)) or not set(actual) <= expected:
            raise ValueError("execution_feedback_command_mismatch")
        if feedback.status == "success" and (set(actual) != expected or any(c.status != "success" for c in feedback.commands)):
            raise ValueError("execution_feedback_incomplete_success")
        scene = self.require_scene()
        if feedback.holding_object is not None and feedback.holding_object not in {o.scene_object_id for o in scene.objects}:
            raise ValueError("execution_feedback_holding_unknown")
        candidate = None
        if confirmed_scene is not None:
            candidate = SceneConfig.model_validate(confirmed_scene.model_dump())
            if candidate.scene_id != scene.scene_id or candidate.scene_version <= scene.scene_version:
                raise ValueError("execution_feedback_scene_mismatch")
            if feedback.holding_object is not None and feedback.holding_object not in {o.scene_object_id for o in candidate.objects}:
                raise ValueError("execution_feedback_holding_unknown")
        if feedback_source not in {"external", "simulated"}:
            raise ValueError("execution_feedback_source_invalid")
        self.sync_state = "unknown"
        if candidate is not None:
            self._check_snapshot(self.platform.load_scene(candidate), candidate)
            self.scene_manager = SceneManager(candidate)
            self.sync_state = "synchronized"
        self.holding_object = feedback.holding_object
        self.last_feedback_source = feedback_source
        self.pending_execution_request = None
        self.pending_commands = None
        return feedback.status
