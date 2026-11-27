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
    SCENE_LAYOUT = "scene_layout"
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

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_observation_hint(cls, value):
        """Read old wire documents without making the hint part of the contract.

        Older Qwen responses may still contain ``requires_fresh_observation``.
        It was a Brain-side policy decision, not a controller capability, so it
        is deliberately ignored during compatibility loading.
        """
        if isinstance(value, dict) and isinstance(value.get("steps"), list):
            value = dict(value)
            value["steps"] = [
                ({k: v for k, v in step.items() if k != "requires_fresh_observation"}
                 if isinstance(step, dict) else step)
                for step in value["steps"]
            ]
        return value

    @model_validator(mode="after")
    def legal_sequence(self):
        # Adjacent arm clauses are merged by execution_segments and planned as
        # one control request. Edits/queries are segment boundaries; the next
        # segment uses the confirmed final scene, never a predicted intermediate
        # pose. An unresolved held object prevents rebuilding another segment.
        if len(self.steps) > 1 and len({step.instruction for step in self.steps}) != len(self.steps):
            # A model that pastes the whole utterance into every step has not
            # split anything; falling back is safer than running it twice.
            raise ValueError("decomposition_steps_repeated")
        return self

    @property
    def composite(self) -> bool:
        return len(self.steps) > 1
