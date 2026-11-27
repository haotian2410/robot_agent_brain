"""The seam between an exported plan and something able to act it out.

The service only ever talks to this port, so the transport (child process today,
possibly an in-process call later) stays an adapter concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from ..contracts.commands_atomic import AtomicCommandsFile
from ..contracts.execution_v41 import ExecutionEnvelopeV41, ExecutionFeedbackV41

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
    # Measured state for passive/articulated scene objects.  Keys are scene
    # object ids and values map RobotDriver joint names to final positions.
    # This is deliberately separate from ``moved``: an articulated drawer's
    # state is not a Transform edit.
    articulated_joints: dict[int, dict[str, float]] = field(default_factory=dict)
    active_joint_ids: list[int] = field(default_factory=list)
    state_verified: bool = False
    no_effect_verified: bool = False
    isolated_workspace_discarded_verified: bool = False
    holding_object: int | None = None
    execution_checkpoint: dict | None = None
    traj_path: str | None = None
    final_scene: dict | None = None
    final_scene_path: str | None = None
    error_code: str | None = None
    detail: str | None = None

    @property
    def summary(self) -> dict:
        return {"ok": self.ok,
                "steps": [{"command_id": step.command_id, "skill_name": step.skill_name,
                           "status": step.status, "error_code": step.error_code} for step in self.steps],
                "moved_object_ids": sorted(self.moved),
                "articulated_joint_object_ids": sorted(self.articulated_joints),
                "state_verified": self.state_verified,
                "no_effect_verified": self.no_effect_verified,
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


class SequenceExecutionPort(Protocol):
    """Proposed separate port; Atomic 2.0 adapters do not implement it."""

    def execute_sequence(self, envelope: ExecutionEnvelopeV41) -> ExecutionFeedbackV41:
        """Requires negotiated 4.1 transport and durable idempotency ledger."""
        ...

    def query_sequence(self, session_id: str, request_id: str) -> ExecutionFeedbackV41:
        """Reconcile the same request after timeout; never implicitly replay."""
        ...
