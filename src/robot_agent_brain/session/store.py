"""Validated local session checkpoints; locks serialize writers on this host."""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from ..adapters.artifact_writer import safe_identifier
from ..contracts.commands import CommandsFile, canonical_commands, parse_commands
from ..contracts.robot_setup import RobotSetup, RobotRuntimeState
from ..contracts.feedback_v3 import ExecutionRecoveryContext
from ..contracts.scene import SceneConfig, SceneId
from ..scene.scene_manager import SceneManager
from .dialogue_state import DialogueState
from .original_scene_store import OriginalSceneManifest, OriginalSceneStore


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["2.0"] = "2.0"
    session_id: str
    revision: int = Field(ge=1)
    config_fingerprint: str | None = None
    scene: SceneConfig | None = None
    dialogue: DialogueState = Field(default_factory=DialogueState)
    session_action: Literal["pause", "resume", "close"] | None = None
    sync_state: Literal["synchronized", "unknown"] = "synchronized"
    session_phase: Literal["setup", "agent_owned"] = "setup"
    camera_id: int | None = None
    holding_object: SceneId | None = None
    robot_setup: RobotSetup | None = None
    robot_setup_revision: int = Field(default=0, strict=True, ge=0)
    arm_states: RobotRuntimeState | None = None
    original_scene_manifest: OriginalSceneManifest | None = None
    platform_object_ids: set[SceneId] | None = None
    profile_object_map: dict[SceneId, SceneId] | None = None
    seen_scene_object_ids: set[SceneId] = Field(default_factory=set)
    # The exhausted sentinel is one past the largest valid Scene ID.
    next_scene_object_id: int = Field(default=0, strict=True, ge=0, le=2**53)
    last_exported_request: str | None = None
    exported_commands: dict[str, dict] = Field(default_factory=dict)
    dispatched_requests: set[str] = Field(default_factory=set)
    pending_commands: dict | None = None
    pending_execution_request: str | None = None
    last_feedback_source: Literal["external", "simulated"] | None = None
    recovery_context: ExecutionRecoveryContext | None = None

    @field_validator("profile_object_map", mode="before")
    @classmethod
    def json_map_keys(cls, value, info):
        if value is not None and info.mode == "json":
            if any(not key.isascii() or not key.isdigit() or str(int(key)) != key for key in value):
                raise ValueError("session_profile_map_key_invalid")
            return {int(key): item for key, item in value.items()}
        return value

    @model_validator(mode="before")
    @classmethod
    def migrate_v1(cls, value):
        if isinstance(value, dict) and value.get("version") == "1.0":
            value = dict(value)
            # Old checkpoints contain neither an explicit deployed binding nor
            # evidence for arm state. Preserve legacy holding without inventing
            # a profile, empty gripper, or historical original snapshot.
            if any(key in value for key in ("robot_setup", "robot_setup_revision", "arm_states", "original_scene_manifest", "platform_object_ids", "profile_object_map", "recovery_context")):
                raise ValueError("session_v1_contains_v2_fields")
            value["version"] = "2.0"
        return value

    @model_validator(mode="after")
    def consistent(self):
        safe_identifier(self.session_id)
        if self.recovery_context is not None:
            recovery = self.recovery_context
            if (self.scene is None or self.robot_setup is None or self.sync_state != "unknown"
                    or self.pending_execution_request is not None or recovery.request_id not in self.dispatched_requests
                    or recovery.robot_setup_revision != self.robot_setup_revision
                    or recovery.scene_id != self.scene.scene_id or recovery.base_scene_version != self.scene.scene_version
                    or recovery.minimum_scene_version <= recovery.base_scene_version):
                raise ValueError("session_recovery_context_invalid")
        known = {o.object_id_in_scene for o in self.scene.objects} if self.scene else set()
        if self.profile_object_map is not None:
            if self.robot_setup is None or not set(self.profile_object_map.values()) <= known or len(set(self.profile_object_map.values())) != len(self.profile_object_map):
                raise ValueError("session_profile_object_map_invalid")
        if self.robot_setup is None:
            if self.arm_states is not None or self.robot_setup_revision != 0:
                raise ValueError("session_robot_setup_missing")
        else:
            if self.robot_setup_revision < 1 or self.arm_states is None or set(self.arm_states.arms) != set(self.robot_setup.arms):
                raise ValueError("session_robot_state_mismatch")
            if not {a.robot_object_id for a in self.robot_setup.arms.values()} <= known:
                raise ValueError("session_robot_object_missing")
            held = [a.holding_object for a in self.arm_states.arms.values() if a.holding_object is not None]
            if not set(held) <= known or len(held) != len(set(held)):
                raise ValueError("session_robot_holding_invalid")
            if self.robot_setup.mode == "dual" and self.holding_object is not None:
                raise ValueError("session_dual_legacy_holding_ambiguous")
            if self.robot_setup.mode == "single" and self.arm_states.arms["single"].holding_object != self.holding_object:
                raise ValueError("session_single_holding_mismatch")
        if not known <= self.seen_scene_object_ids or self.next_scene_object_id <= max(self.seen_scene_object_ids, default=-1):
            raise ValueError("session_state_allocator_invalid")
        focus = self.dialogue.last_entity_ids + ([self.dialogue.last_entity_id] if self.dialogue.last_entity_id is not None else [])
        if not set(focus) <= known or self.holding_object is not None and self.holding_object not in known:
            raise ValueError("session_state_unknown_object")
        for request, payload in self.exported_commands.items():
            command = parse_commands(payload)
            if command.request_id != request or canonical_commands(command) != payload:
                raise ValueError("session_state_invalid_export")
        if self.last_exported_request is not None and self.last_exported_request not in self.exported_commands:
            raise ValueError("session_state_last_export_missing")
        if (self.pending_execution_request is None) != (self.pending_commands is None):
            raise ValueError("session_state_pending_mismatch")
        if self.pending_commands is not None:
            request = self.pending_execution_request
            command = parse_commands(self.pending_commands)
            if command.schema_version == "3.0" and (command.robot_setup != self.robot_setup or command.robot_setup_revision != self.robot_setup_revision):
                raise ValueError("session_state_pending_setup_mismatch")
            if (request not in self.dispatched_requests or self.exported_commands.get(request) != self.pending_commands
                    or command.request_id != request or self.scene is None
                    or (command.scene_id, command.scene_version) != (self.scene.scene_id, self.scene.scene_version)):
                raise ValueError("session_state_pending_mismatch")
        return self


class SessionStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def directory(self, session_id):
        path = self.root / safe_identifier(session_id)
        self.root.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("session_path_escape")
        path.mkdir(exist_ok=True)
        if path.resolve().parent != self.root:
            raise ValueError("session_path_escape")
        return path

    @contextmanager
    def lock(self, session_id):
        # POSIX advisory lock; never steal a live writer's lock. Process exit
        # releases it, unlike a stale directory sentinel. No network FS claim.
        import fcntl
        path = self.directory(session_id) / ".session.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("session_busy") from exc
            yield
        finally:
            os.close(fd)

    def load(self, session_id):
        path = self.directory(session_id) / "session_state.json"
        if path.is_symlink():
            raise ValueError("session_path_escape")
        if not path.exists():
            return None
        state = SessionState.model_validate_json(path.read_text(encoding="utf-8"))
        if state.session_id != session_id:
            raise ValueError("session_state_identity_mismatch")
        if state.original_scene_manifest is not None:
            OriginalSceneStore(path.parent).load(state.original_scene_manifest)
        return state

    def save(self, session_id, session, *, revision, config_fingerprint=None):
        """Caller holds lock across restore, processing, and this checkpoint."""
        state = SessionState(session_id=session_id, revision=revision, config_fingerprint=config_fingerprint, scene=session.scene,
            seen_scene_object_ids=session.seen_scene_object_ids, next_scene_object_id=session.next_scene_object_id,
            dialogue=session.dialogue, session_action=session.session_action, sync_state=session.sync_state,
            session_phase=getattr(session, "session_phase", "setup"), camera_id=getattr(session, "camera_id", None),
            holding_object=session.holding_object, last_exported_request=session.last_exported_request,
            robot_setup=session.robot_setup, robot_setup_revision=session.robot_setup_revision, arm_states=session.arm_states,
            original_scene_manifest=session.original_scene_manifest, platform_object_ids=session.platform_object_ids,
            profile_object_map=session.profile_object_map,
            exported_commands=session.exported_commands, dispatched_requests=session.dispatched_requests,
            pending_commands=session.pending_commands, pending_execution_request=session.pending_execution_request,
            last_feedback_source=getattr(session, "last_feedback_source", None), recovery_context=session.recovery_context)
        parent = self.directory(session_id)
        fd, temporary = tempfile.mkstemp(prefix=".state-", dir=parent)
        try:
            encoded = state.model_dump(mode="json")
            # Preserve the lossless Scene document's omission of the optional zero sub-version.
            # Pydantic's nested serializer materializes defaults, which otherwise turns an
            # unchanged scene into a different raw document after restart and trips the browser
            # scene-digest/version gate.
            if session.scene is not None and "scene_sub_version" not in session.scene.raw_document():
                encoded["scene"].pop("scene_sub_version", None)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(encoded, ensure_ascii=False, allow_nan=False))
                stream.flush()
                os.fsync(stream.fileno())
            check = SessionState.model_validate_json(Path(temporary).read_text(encoding="utf-8"))
            if check.model_dump(mode="json") != state.model_dump(mode="json"):
                raise ValueError("session_state_readback_mismatch")
            os.replace(temporary, parent / "session_state.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state.revision

    @staticmethod
    def restore(state, session):
        if state.scene is not None:
            session._validate_identity_range(state.scene)
            # A checkpoint is not authoritative evidence of post-execution
            # geometry. Restore gates/metadata without resetting the platform.
            if (state.sync_state == "synchronized" and state.pending_execution_request is None
                    and not getattr(session.platform, "restore_read_only", False)):
                session.initialize_scene(state.scene)
            session._commit_manager(SceneManager(state.scene,
                seen_scene_object_ids=state.seen_scene_object_ids, next_scene_object_id=state.next_scene_object_id))
        else:
            session.seen_scene_object_ids = set(state.seen_scene_object_ids)
            session.next_scene_object_id = state.next_scene_object_id
        for name in ("dialogue", "session_action", "sync_state", "session_phase", "camera_id", "holding_object", "last_exported_request",
                     "exported_commands", "dispatched_requests", "pending_commands", "pending_execution_request",
                     "last_feedback_source", "recovery_context"):
            setattr(session, name, getattr(state.model_copy(deep=True), name))
        for name in ("robot_setup", "robot_setup_revision", "arm_states", "original_scene_manifest", "platform_object_ids", "profile_object_map"):
            setattr(session, name, getattr(state.model_copy(deep=True), name))
        session.last_request_id = state.last_exported_request
        return session
