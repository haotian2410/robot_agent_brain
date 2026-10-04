from typing import Protocol
from ..contracts.commands import CommandsFile


class CommandSinkPort(Protocol):
    def write(self, commands: CommandsFile) -> None: ...

