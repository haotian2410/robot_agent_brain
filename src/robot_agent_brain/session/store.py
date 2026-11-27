"""Validated local session checkpoints; locks serialize writers on this host."""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from ..perf_trace import timed
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator, field_serializer
from ..adapters.artifact_writer import safe_identifier
from ..filelock import lock_exclusive
from ..contracts.commands import CommandsFile, canonical_commands, parse_commands
from ..contracts.robot_setup import RobotSetup, RobotRuntimeState
from ..contracts.robot_mode_lock import RobotModeLock
from ..contracts.feedback_v3 import ExecutionRecoveryContext
from ..contracts.scene import SceneConfig, SceneId, parse_scene_document
from ..scene.scene_manager import SceneManager
from .dialogue_state import DialogueState
from .original_scene_store import OriginalSceneManifest, OriginalSceneStore
from .conversation_memory import ConversationMemory
from .conversation_memory import StepLedgerEntry


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
    execution_checkpoint: dict | None = None
    execution_reconciliation: dict | None = None
    robot_setup: RobotSetup | None = None
    robot_setup_revision: int = Field(default=0, strict=True, ge=0)
    robot_mode_lock: RobotModeLock | None = None
    session_turn_index: int = Field(default=0, strict=True, ge=0)
    first_accepted_turn_id: str | None = None
    first_robot_mode_turn_id: str | None = None
    mode_lifecycle_version: Literal[1] = 1
    mode_migration_diagnostics: list[str] = Field(default_factory=list)
    platform_rebind_revision: int = Field(default=0, strict=True, ge=0)
    robot_asset: str | None = None
    gripper_asset: str | None = None
    camera_asset: str | None = None
    execution_capability: Literal["unknown", "supported", "unsupported"] = "unknown"
    arm_states: RobotRuntimeState | None = None
    original_scene_manifest: OriginalSceneManifest | None = None
    platform_object_ids: set[SceneId] | None = None
    profile_object_map: dict[SceneId, SceneId] | None = None
    seen_scene_object_ids: set[SceneId] = Field(default_factory=set)
    # The exhausted sentinel is one past the largest valid Scene ID.
    next_scene_object_id: int = Field(default=0, strict=True, ge=0, le=2**53)
    last_exported_request: str | None = None
    exported_commands: dict[str, dict] = Field(default_factory=dict)
    # Historical plans are retained for audit/download but are never eligible
    # for dispatch after a later successful Scene commit.
    stale_commands: dict[str, dict] = Field(default_factory=dict)
    dispatched_requests: set[str] = Field(default_factory=set)
    pending_commands: dict | None = None
    pending_execution_request: str | None = None
    last_feedback_source: Literal["external", "simulated"] | None = None
    recovery_context: ExecutionRecoveryContext | None = None
    conversation_memory: ConversationMemory = Field(default_factory=ConversationMemory)
    prefer_auto_resolve: bool = False
    pending_step_ledger: list[StepLedgerEntry] = Field(default_factory=list)
    arrangement_records: list[dict] = Field(default_factory=list)
    layout_request_receipts: dict[str, dict[str, str]] = Field(default_factory=dict)
    layout_id_reservations: dict[str, tuple[int, int]] = Field(default_factory=dict)
    composite_turn_records: list[dict] = Field(default_factory=list)

    @field_validator("layout_id_reservations", mode="before")
    @classmethod
    def strict_reservation_ranges(cls, value):
        if not isinstance(value, dict) or any(
                not isinstance(pair, (tuple, list)) or len(pair) != 2
                or any(type(item) is not int for item in pair) for pair in value.values()):
            raise ValueError("session_layout_reservation_invalid")
        return value

    @field_validator("scene", mode="before")
    @classmethod
    def decode_scene_document(cls, value):
        if isinstance(value, dict):
            document = parse_scene_document(value, uint32=False)
            if document.rejected_objects:
                raise ValueError("session_scene_objects_rejected")
            return document.view
        return value

    @field_serializer("scene")
    def encode_scene_document(self, value):
        return None if value is None else value.raw_document()

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

    @model_validator(mode="before")
    @classmethod
    def migrate_mode_lifecycle(cls, value):
        if not isinstance(value, dict) or "mode_lifecycle_version" in value:
            return value
        value = dict(value)
        value["mode_lifecycle_version"] = 1
        diagnostics = list(value.get("mode_migration_diagnostics", []))
        memory = value.get("conversation_memory") or {}
        turns = memory.get("recent_turns", [])
        evidence = (value.get("last_exported_request") or value.get("pending_execution_request")
                    or next(iter(value.get("exported_commands", {})), None)
                    or next(iter(value.get("stale_commands", {})), None)
                    or next(iter(value.get("dispatched_requests", [])), None))
        if evidence is None:
            evidence = next((turn["turn_id"] for turn in turns if
                turn.get("executed") or turn.get("final_outcome") in {"plan_ready", "robot_configured"}), None)
        lock = value.get("robot_mode_lock")
        if isinstance(lock, RobotModeLock):
            lock = lock.model_dump()
        uncertain = (value.get("sync_state") == "unknown" or value.get("pending_execution_request")
                     or value.get("recovery_context"))
        complete_nonrobot = (bool(turns) and value.get("session_turn_index") == len(turns)
                            and not memory.get("archived_turn_ids") and not uncertain
                            and value.get("first_accepted_turn_id") in {t["turn_id"] for t in turns}
                            and all(t.get("final_outcome") in {"scene_updated", "answered", "session_controlled"}
                                    and not t.get("executed") for t in turns))
        if evidence:
            setup = value.get("robot_setup")
            if isinstance(setup, RobotSetup):
                setup = setup.model_dump()
            if lock is None:
                lock = {"mode": setup["mode"] if setup else "single",
                        "profile_id": setup["profile_id"] if setup else "default_single",
                        "source": "scene" if setup else "default",
                        "setup_revision": value.get("robot_setup_revision", 0)}
            lock = {**lock, "locked": True, "locked_at_turn": lock.get("locked_at_turn") or 1}
            value["first_robot_mode_turn_id"] = evidence
            value["session_turn_index"] = max(value.get("session_turn_index", 0), lock["locked_at_turn"])
            value["first_accepted_turn_id"] = value.get("first_accepted_turn_id") or evidence
            diagnostics.append("mode_migration_verified_robot_history")
        elif lock and lock.get("locked"):
            if complete_nonrobot:
                lock = {**lock, "locked": False, "locked_at_turn": None}
                diagnostics.append("mode_migration_nonrobot_mislock_removed")
            else:
                # Keep the old decision when the audit trail is incomplete.
                value["first_robot_mode_turn_id"] = value.get("first_accepted_turn_id") or "historical_mode_decision_unknown"
                diagnostics.append("mode_migration_history_incomplete_lock_preserved")
        value["robot_mode_lock"] = lock
        value["mode_migration_diagnostics"] = diagnostics
        return value

    @model_validator(mode="after")
    def consistent(self):
        safe_identifier(self.session_id)
        if self.robot_mode_lock is not None:
            self.robot_mode_lock.check_setup(self.robot_setup, self.robot_setup_revision)
            if self.robot_mode_lock.locked:
                if (self.robot_mode_lock.locked_at_turn > self.session_turn_index
                        or self.first_robot_mode_turn_id is None):
                    raise ValueError("session_mode_lock_turn_mismatch")
        if self.first_robot_mode_turn_id is not None and not (self.robot_mode_lock and self.robot_mode_lock.locked):
            raise ValueError("session_robot_mode_decision_without_lock")
        ranges = sorted(self.layout_id_reservations.values())
        for index, (start, end) in enumerate(ranges):
            if (not 0 <= start < end <= self.next_scene_object_id or end - start > 1000
                    or (index and ranges[index - 1][1] > start)):
                raise ValueError("session_layout_reservation_invalid")
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
            if (self.arm_states is not None or (self.robot_setup_revision != 0
                    and (self.platform_rebind_revision < 1 or self.robot_setup_revision < self.platform_rebind_revision))):
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
        for request, payload in self.stale_commands.items():
            command = parse_commands(payload)
            if command.request_id != request or canonical_commands(command) != payload:
                raise ValueError("session_state_invalid_stale_export")
        if self.last_exported_request is not None and self.last_exported_request not in self.exported_commands:
            raise ValueError("session_state_last_export_missing")
        if (self.pending_execution_request is None) != (self.pending_commands is None):
            raise ValueError("session_state_pending_mismatch")
        if self.pending_commands is not None:
            request = self.pending_execution_request
            command = parse_commands(self.pending_commands)
            if command.schema_version == "4.1":
                raise ValueError("session_v41_pending_adapter_unavailable")
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
        path = self.directory(session_id) / ".session.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                lock_exclusive(fd)
            except BlockingIOError as exc:
                raise ValueError("session_busy") from exc
            yield
        finally:
            os.close(fd)

    @timed("store.load", component="brain.session")
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

    @timed("store.save", component="brain.session")
    def save(self, session_id, session, *, revision, config_fingerprint=None):
        """Caller holds lock across restore, processing, and this checkpoint."""
        state = SessionState(session_id=session_id, revision=revision, config_fingerprint=config_fingerprint, scene=session.scene,
            seen_scene_object_ids=session.seen_scene_object_ids, next_scene_object_id=session.next_scene_object_id,
            dialogue=session.dialogue, session_action=session.session_action, sync_state=session.sync_state,
            session_phase=getattr(session, "session_phase", "setup"), camera_id=getattr(session, "camera_id", None),
            holding_object=session.holding_object, platform_rebind_revision=getattr(session, "platform_rebind_revision", 0),
            execution_checkpoint=getattr(session, "execution_checkpoint", None),
            execution_reconciliation=session.execution_reconciliation,
            robot_asset=getattr(session, "robot_asset", None), gripper_asset=getattr(session, "gripper_asset", None),
            camera_asset=getattr(session, "camera_asset", None), execution_capability=getattr(session, "execution_capability", "unknown"),
            last_exported_request=session.last_exported_request,
            robot_setup=session.robot_setup, robot_setup_revision=session.robot_setup_revision, arm_states=session.arm_states,
            robot_mode_lock=session.robot_mode_lock, session_turn_index=session.session_turn_index,
            first_accepted_turn_id=session.first_accepted_turn_id,
            first_robot_mode_turn_id=session.first_robot_mode_turn_id,
            mode_lifecycle_version=session.mode_lifecycle_version,
            mode_migration_diagnostics=session.mode_migration_diagnostics,
            original_scene_manifest=session.original_scene_manifest, platform_object_ids=session.platform_object_ids,
            profile_object_map=session.profile_object_map,
            exported_commands=session.exported_commands, dispatched_requests=session.dispatched_requests,
            stale_commands=getattr(session, "stale_commands", {}),
            pending_commands=session.pending_commands, pending_execution_request=session.pending_execution_request,
            last_feedback_source=getattr(session, "last_feedback_source", None), recovery_context=session.recovery_context)
        state.conversation_memory = session.conversation_memory.model_copy(deep=True)
        state.prefer_auto_resolve = bool(getattr(session, "prefer_auto_resolve", False))
        state.pending_step_ledger = [item.model_copy(deep=True) for item in getattr(session, "pending_step_ledger", [])]
        state.arrangement_records = session.arrangement_index.snapshot()
        state.layout_request_receipts = {key: dict(value) for key, value in session.layout_request_receipts.items()}
        state.layout_id_reservations = {key: tuple(value) for key, value in session.layout_id_reservations.items()}
        state.composite_turn_records = [dict(item) for item in getattr(session, "composite_turn_records", [])]
        parent = self.directory(session_id)
        fd, temporary = tempfile.mkstemp(prefix=".state-", dir=parent)
        try:
            encoded = state.model_dump(mode="json")
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(encoded, ensure_ascii=False, allow_nan=False))
                stream.flush()
                os.fsync(stream.fileno())
            check = SessionState.model_validate_json(Path(temporary).read_text(encoding="utf-8"))
            if state.scene is not None and (check.scene is None
                    or state.scene.raw_document() != check.scene.raw_document()):
                raise ValueError("session_state_readback_mismatch: scene_document")
            if state != check:
                # The dumps of two *equal* states can still differ: a set built by incremental
                # adds iterates in its own table order, and a reload from the written list can
                # rebuild that same content in another sequence.  Comparing documents therefore
                # invented a mismatch out of a set field (``dispatched_requests`` after a
                # multi-step round), aborted the rename, and the task reported 会话保存失败 over
                # the real verdict.  Compare the states, and name the offenders set-aware.
                def comparable(value):
                    return sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
                offenders = sorted(name for name in type(state).model_fields
                                   if comparable(getattr(state, name, None))
                                   != comparable(getattr(check, name, None)))
                raise ValueError("session_state_readback_mismatch: " + ",".join(offenders))
            os.replace(temporary, parent / "session_state.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state.revision

    @staticmethod
    def restore(state, session):
        # A crash after reservation but before publication must not resurrect
        # those IDs. Current committed members remain legal existing objects.
        state = state.model_copy(deep=True)
        for bounds in state.layout_id_reservations.values():
            state.seen_scene_object_ids.update(range(*bounds))
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
        for name in ("dialogue", "session_action", "sync_state", "session_phase", "camera_id", "holding_object", "execution_checkpoint", "execution_reconciliation",
                     "platform_rebind_revision", "robot_asset", "gripper_asset", "camera_asset", "execution_capability", "last_exported_request",
                     "exported_commands", "dispatched_requests", "pending_commands", "pending_execution_request",
                     "stale_commands",
                     "last_feedback_source", "recovery_context", "conversation_memory", "prefer_auto_resolve",
                     "pending_step_ledger"):
            setattr(session, name, getattr(state.model_copy(deep=True), name))
        session.composite_turn_records = [dict(item) for item in state.composite_turn_records]
        session.layout_request_receipts = {key: dict(value) for key, value in state.layout_request_receipts.items()}
        session.layout_id_reservations = {key: list(value) for key, value in state.layout_id_reservations.items()}
        from ..scene.arrangement_index import ArrangementIndex, ArrangementRecord
        session.arrangement_index = ArrangementIndex()
        for item in state.arrangement_records:
            session.arrangement_index.put(ArrangementRecord.model_validate(item))
        for name in ("robot_setup", "robot_setup_revision", "arm_states", "original_scene_manifest", "platform_object_ids", "profile_object_map"):
            setattr(session, name, getattr(state.model_copy(deep=True), name))
        session.robot_mode_lock = state.robot_mode_lock
        session.session_turn_index = state.session_turn_index
        session.first_accepted_turn_id = state.first_accepted_turn_id
        session.first_robot_mode_turn_id = state.first_robot_mode_turn_id
        session.mode_lifecycle_version = state.mode_lifecycle_version
        session.mode_migration_diagnostics = list(state.mode_migration_diagnostics)
        session.last_request_id = state.last_exported_request
        return session
