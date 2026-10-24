"""Durable publication facts, separate from external platform transactions."""
import json
import os
import tempfile
from pathlib import Path

from ..adapters.artifact_writer import safe_identifier
from ..filelock import sync_directory


class PublicationStore:
    def __init__(self, directory):
        self.directory = Path(directory) / "publication_records"

    def path(self, request_id):
        if self.directory.is_symlink():
            raise ValueError("publication_path_escape")
        path = self.directory / (safe_identifier(request_id) + ".json")
        if path.is_symlink():
            raise ValueError("publication_path_escape")
        return path

    def write(self, record):
        path = self.path(record["request_id"])
        self.directory.mkdir(exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".publication-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            for directory in (self.directory, self.directory.parent):
                sync_directory(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def read(self, request_id):
        value = json.loads(self.path(request_id).read_text(encoding="utf-8"))
        if value.get("request_id") != request_id:
            raise ValueError("publication_record_identity_mismatch")
        return value

    def require_checkpoint(self, state):
        if self.directory.is_symlink():
            raise ValueError("publication_path_escape")
        for path in self.directory.glob("*.json"):
            record = self.read(path.stem)
            if record["scene_commit_status"] in {"committed", "unknown"} and (
                    state is None or state.revision < record["checkpoint_revision"]):
                raise ValueError("publication_recovery_required: " + record["request_id"])
