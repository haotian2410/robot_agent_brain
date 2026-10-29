import json
from pathlib import Path

import pytest

from robot_agent_brain.errors import BrainError
from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.models.protocol_migration import compare_v2_v3
from robot_agent_brain.grounding.scene_reference_resolver import SceneReferenceResolver


GOLDENS = json.loads((Path(__file__).parent / "fixtures/task_understanding_goldens.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", GOLDENS, ids=lambda case: case["name"])
def test_canonical_protocol_goldens(case):
    turn = parse_qwen_turn(case["payload"], case["instruction"])
    expected = case["expect"]
    assert turn.turn_kind.value == expected["turn_kind"]
    if expected.get("canonical_reference"):
        assert turn.scene_edit.scene_refs[0].canonical_value == expected["canonical_reference"]
    if expected.get("entity_reference"):
        assert turn.scene_edit.operations[0].reference == expected["entity_reference"]
    if expected.get("error"):
        with pytest.raises(BrainError, match=expected["error"]):
            SceneReferenceResolver().resolve(expected.get("raw", "window"), entities=[], scene=None)


def test_aliases_normalize_stably():
    resolver = SceneReferenceResolver()
    assert {resolver.catalog.canonical(value) for value in ("table", "desk", "desktop", "桌子", "桌面", "台面")} == {"table"}


def test_unknown_reference_never_binds_to_default_surface():
    with pytest.raises(BrainError, match="scene_reference_unresolved"):
        SceneReferenceResolver().resolve("window", entities=[], scene=None, default_surface_id=0)


def test_v2_v3_shadow_comparison_uses_canonical_payload():
    case = GOLDENS[0]
    v2 = json.loads(json.dumps(case["payload"]))
    v3 = json.loads(json.dumps(case["payload"]))
    v2["protocol_version"] = "task_understanding.v2"
    v3["protocol_version"] = "task_understanding.v3"
    comparison = compare_v2_v3(v2, v3, case["instruction"])
    assert comparison["equivalent"] is True
    assert comparison["v2"]["protocol_version"] == "task_understanding.v2"
    assert comparison["v3"]["protocol_version"] == "task_understanding.v3"
