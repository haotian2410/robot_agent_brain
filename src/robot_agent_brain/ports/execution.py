"""The seam between an exported plan and something able to act it out.

The service only ever talks to this port, so the transport (child process today,
possibly an in-process call later) stays an adapter concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from ..contracts.commands_atomic import AtomicCommandsFile

StepStatus = Literal["success", "failed"]


@dataclass
class ExecutionStep:
    command_id: str
    skill_name: str
    status: StepStatus
    error_code: str | None = None
    detail: str | None = None


@dataclass
class ExecutionOutcome:
    """What one runner call established about one exported command document.

    ``moved`` is keyed by ``object_id_in_scene`` and holds only objects whose
    pose actually changed, which is what keeps an unchanged table from being
    written back as an edit.
    """
    ok: bool
    steps: list[ExecutionStep] = field(default_factory=list)
    moved: dict[int, dict] = field(default_factory=dict)
    holding_object: int | None = None
    traj_path: str | None = None
    error_code: str | None = None
    detail: str | None = None

    @property
    def summary(self) -> dict:
        return {"ok": self.ok,
                "steps": [{"command_id": step.command_id, "skill_name": step.skill_name,
                           "status": step.status, "error_code": step.error_code} for step in self.steps],
                "moved_object_ids": sorted(self.moved),
                "holding_object": self.holding_object,
                "trajectory_available": self.traj_path is not None,
                "error_code": self.error_code}


class ExecutionPort(Protocol):
    def run(self, commands: AtomicCommandsFile, scene_document: dict, *,
            progress: Callable[[list[ExecutionStep]], None] | None = None) -> ExecutionOutcome:
        """Act out ``commands`` against ``scene_document`` and report the result.

        The scene document is the browser's own, forwarded unchanged: the runner
        that assembles a robot from it must see the same bytes the editor is
        looking at, or the three copies of the scene identity the control side
        compares would disagree.  ``progress`` sees the commands the runner has
        already finished, which is the only way to answer "how far along is it"
        while a task holds the browser frozen.
        """
        ...
