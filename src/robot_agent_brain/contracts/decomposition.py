"""One utterance, several ordered tasks.

A decomposition is a plan for a *sequence* of ordinary turns, never a wider
turn: :meth:`BrainTurn.one_payload` still governs each step, so the split is
only legal when every piece could have been said on its own.  Anything that
fails that test falls back to the single-turn path, which is the behaviour
deployments had before this file existed.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# A 「把苹果放进篮子，再拿出来放桌子左边，再新增一个香蕉……」 sentence is five real
# clauses, so the old four-step ceiling refused it outright.  Six is still short
# enough that 「停在第 6 步」 reads better than the utterance it explains.
MAX_SUBTASKS = 6


class SubtaskKind(StrEnum):
    SCENE_EDIT = "scene_edit"
    ROBOT_TASK = "robot_task"
    SCENE_QUERY = "scene_query"


class Subtask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: SubtaskKind
    instruction: str = Field(min_length=1)

    @model_validator(mode="after")
    def trimmed(self):
        self.instruction = self.instruction.strip()
        if not self.instruction:
            raise ValueError("decomposition_step_instruction_empty")
        return self


class TaskDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[Subtask] = Field(min_length=1, max_length=MAX_SUBTASKS)

    @model_validator(mode="after")
    def legal_sequence(self):
        # Several arm tasks in one utterance are legal because each dispatch commits
        # the executed poses back to the browser before the next one is understood:
        # the second run rebuilds its simulator from the world the first run left,
        # which is exactly the intermediate state the user asked for in sequence.
        # What must not happen is a run that leaves the gripper occupied -- the next
        # rebuild starts with empty fingers -- and the orchestrator stops the walk
        # there rather than chaining onto it.
        if len(self.steps) > 1 and len({step.instruction for step in self.steps}) != len(self.steps):
            # A model that pastes the whole utterance into every step has not
            # split anything; falling back is safer than running it twice.
            raise ValueError("decomposition_steps_repeated")
        return self

    @property
    def composite(self) -> bool:
        return len(self.steps) > 1
