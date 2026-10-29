"""Small, deterministic helpers for task-understanding v2/v3 migration.

The comparison deliberately ignores the wire envelope version and compares the
canonical BrainTurn payload.  It is useful for shadow evaluation and does not
change the live execution path or silently select one model response over the
other.
"""
from __future__ import annotations

from typing import Any

from .task_understanding import parse_qwen_turn


def canonical_turn_signature(turn) -> dict[str, Any]:
    """Return stable semantic fields used by v2/v3 comparison tooling."""
    value = turn.model_dump(mode="json")
    value.pop("protocol_version", None)
    value.pop("instruction", None)
    return value


def compare_v2_v3(v2_payload: dict[str, Any], v3_payload: dict[str, Any], instruction: str) -> dict[str, Any]:
    """Parse both envelopes and report canonical equivalence/differences.

    Parsing errors are returned as structured evidence instead of being
    swallowed.  Callers can use this in offline shadow evaluation without
    allowing the comparison result to affect the selected live turn.
    """
    result: dict[str, Any] = {"equivalent": False, "differences": [], "v2": {}, "v3": {}}
    for label, payload in (("v2", v2_payload), ("v3", v3_payload)):
        try:
            turn = parse_qwen_turn(payload, instruction)
            result[label] = {
                "protocol_version": turn.protocol_version,
                "signature": canonical_turn_signature(turn),
            }
        except Exception as exc:  # evidence must preserve the exact migration failure
            result[label] = {"error": {"type": type(exc).__name__, "message": str(exc)}}
    if "signature" in result["v2"] and "signature" in result["v3"]:
        if result["v2"]["signature"] == result["v3"]["signature"]:
            result["equivalent"] = True
        else:
            result["differences"].append("canonical_payload")
    else:
        result["differences"].append("parse_result")
    return result
