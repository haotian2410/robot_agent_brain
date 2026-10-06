from pathlib import Path
import json
import os
import tempfile
from ..contracts.commands import CommandsFile, canonical_commands


class JsonCommandSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def write(self, commands: CommandsFile) -> None:
        payload = canonical_commands(commands)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staged = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".commands-", delete=False) as stream:
                staged = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            readback = json.loads(staged.read_text(encoding="utf-8"))
            if canonical_commands(CommandsFile.model_validate(readback)) != payload:
                raise ValueError("commands_readback_mismatch")
            os.replace(staged, self.path)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
