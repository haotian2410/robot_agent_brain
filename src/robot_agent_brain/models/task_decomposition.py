"""The decomposition stage: one utterance to an ordered list of ordinary turns.

Deliberately narrow.  It never carries entity, asset or geometry data, because
each step is re-understood by the existing route as if the user had said it
alone.  Anything this stage cannot express must fall back to the single-turn
path rather than be squeezed into a step.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..contracts.decomposition import MAX_SUBTASKS, SubtaskKind, TaskDecomposition

KINDS = [kind.value for kind in SubtaskKind]

# The words that make a second model round worth its latency.  A false positive
# costs one small completion; a false negative only ever costs the user the
# clarification they would have got from the single-turn path anyway.
SEQUENCING_MARKERS = ("然后", "接着", "之后", "最后", "先", "再", "顺便", "并且", "同时",
                      # “并把/并将/并让” are the compact Chinese form of a
                      # second imperative clause.  Plain “并” is deliberately
                      # not included: expressions such as “并不存在” are not
                      # composite tasks.
                      "并把", "并将", "并让",
                      "then", "after that", "finally")


def worth_splitting(instruction: str) -> bool:
    """Whether this utterance reads as more than one task.

    Two finished sentences are a sequence even without a connective, which is
    why the period count joins the marker test.
    """
    text = instruction.strip()
    return (any(marker in text for marker in SEQUENCING_MARKERS)
            or sum(text.count(char) for char in "。；;") >= 2)


def preserve_explicit_pronoun_step(instruction: str, value: TaskDecomposition) -> TaskDecomposition:
    """Keep an explicit pronoun from the user's second clause.

    The decomposition model is not allowed to resolve dialogue references.  A
    common failure is rewriting ``并把他...`` as ``把苹果...`` while otherwise
    returning a valid two-step document.  For the unambiguous two-clause form,
    use the user's own clause verbatim; this is not asset or object guessing.
    More complex sentences are left untouched and are handled by the normal
    dialogue/clarification path.
    """
    if len(value.steps) != 2:
        return value
    match = re.search(r"并(?P<clause>(?:把|将|让)[^。；;]*)", instruction)
    if match is None:
        return value
    clause = match.group("clause").strip()
    if not re.search(r"(?<!其)(?:它|他|她)(?!们)", clause):
        return value
    if re.search(r"(?<!其)(?:它|他|她)(?!们)", value.steps[1].instruction):
        return value
    steps = list(value.steps)
    steps[1] = steps[1].model_copy(update={"instruction": clause})
    return value.model_copy(update={"steps": steps})


class TaskDecompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1)
    scene_context: dict[str, Any] = Field(default_factory=dict)


def task_decomposition_wire_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_SUBTASKS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "instruction"],
                    "properties": {
                        "kind": {"type": "string", "enum": KINDS},
                        "instruction": {"type": "string", "minLength": 1},
                    },
                },
            }
        },
    }


def parse_decomposition(value: Any) -> TaskDecomposition:
    """Wire output to the canonical contract, with no repair of the model's words."""
    if isinstance(value, list):
        value = {"steps": value}
    return TaskDecomposition.model_validate(value)
