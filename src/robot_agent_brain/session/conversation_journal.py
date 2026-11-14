"""Append-by-turn journal for the user-facing conversation view."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..adapters.artifact_writer import safe_identifier


class ConversationJournal:
    def __init__(self, session_root):
        self.root = Path(session_root).resolve() / "conversation" / "turns"
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, turn_id: str, value: dict) -> Path:
        path = self.root / f"{safe_identifier(turn_id)}.json"
        fd, temporary = tempfile.mkstemp(prefix=".turn-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return path
