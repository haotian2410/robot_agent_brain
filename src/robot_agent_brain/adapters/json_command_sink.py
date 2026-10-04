from pathlib import Path
from ..contracts.commands import CommandsFile


class JsonCommandSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def write(self, commands: CommandsFile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(commands.model_dump_json(indent=2), encoding="utf-8")

