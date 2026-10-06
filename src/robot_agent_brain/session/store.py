"""Validated local session checkpoints; locks serialize writers on this host."""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..adapters.artifact_writer import safe_identifier
from ..contracts.commands import CommandsFile, canonical_commands
from ..contracts.scene import SceneConfig
from .dialogue_state import DialogueState


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1.0"] = "1.0"
    session_id: str
    revision: int = Field(ge=1)
    scene: SceneConfig | None = None
    dialogue: DialogueState = Field(default_factory=DialogueState)
    session_action: Literal["pause", "resume", "close"] | None = None
    sync_state: Literal["synchronized", "unknown"] = "synchronized"
    holding_object: str | None = None
    last_exported_request: str | None = None
    exported_commands: dict[str, dict] = Field(default_factory=dict)
    dispatched_requests: set[str] = Field(default_factory=set)
    pending_commands: dict | None = None
    pending_execution_request: str | None = None
    last_feedback_source: Literal["external", "simulated"] | None = None

    @model_validator(mode="after")
    def consistent(self):
        safe_identifier(self.session_id)
        known = {o.scene_object_id for o in self.scene.objects} if self.scene else set()
        focus = self.dialogue.last_entity_ids + ([self.dialogue.last_entity_id] if self.dialogue.last_entity_id else [])
        if not set(focus) <= known or self.holding_object is not None and self.holding_object not in known:
            raise ValueError("session_state_unknown_object")
        for request, payload in self.exported_commands.items():
            command = CommandsFile.model_validate(payload)
            if command.request_id != request or canonical_commands(command) != payload:
                raise ValueError("session_state_invalid_export")
        if self.last_exported_request is not None and self.last_exported_request not in self.exported_commands:
            raise ValueError("session_state_last_export_missing")
        if (self.pending_execution_request is None) != (self.pending_commands is None):
            raise ValueError("session_state_pending_mismatch")
        if self.pending_commands is not None:
            request = self.pending_execution_request
            command = CommandsFile.model_validate(self.pending_commands)
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
        return state

    def save(self, session_id, session, *, revision):
        """Caller holds lock across restore, processing, and this checkpoint."""
        state = SessionState(session_id=session_id, revision=revision, scene=session.scene,
            dialogue=session.dialogue, session_action=session.session_action, sync_state=session.sync_state,
            holding_object=session.holding_object, last_exported_request=session.last_exported_request,
            exported_commands=session.exported_commands, dispatched_requests=session.dispatched_requests,
            pending_commands=session.pending_commands, pending_execution_request=session.pending_execution_request,
            last_feedback_source=getattr(session, "last_feedback_source", None))
        parent = self.directory(session_id)
        fd, temporary = tempfile.mkstemp(prefix=".state-", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, allow_nan=False))
                stream.flush()
                os.fsync(stream.fileno())
            check = SessionState.model_validate_json(Path(temporary).read_text(encoding="utf-8"))
            if check != state:
                raise ValueError("session_state_readback_mismatch")
            os.replace(temporary, parent / "session_state.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state.revision

    @staticmethod
    def restore(state, session):
        if state.scene is not None:
            session.initialize_scene(state.scene)
        for name in ("dialogue", "session_action", "sync_state", "holding_object", "last_exported_request",
                     "exported_commands", "dispatched_requests", "pending_commands", "pending_execution_request",
                     "last_feedback_source"):
            setattr(session, name, getattr(state.model_copy(deep=True), name))
        session.last_request_id = state.last_exported_request
        return session
