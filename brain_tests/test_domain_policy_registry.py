import json

import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import PlacementGoal, SceneEditIntent, SceneEditPlan
from robot_agent_brain.semantics.domain_policy_registry import DomainPolicyRegistry


def test_registry_is_single_source_for_scene_relations_and_aliases():
    registry = DomainPolicyRegistry()
    assert {"on", "near", "inside", "behind"} <= registry.supported_scene_relations()
    assert registry.reference_catalog.canonical("桌面") == "table"


def test_same_turn_dependencies_are_stable_and_prior_only():
    plan = SceneEditPlan(
        entities=[
            {"entity_id": "basket", "semantic_name": "basket", "category": "container"},
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
        ],
        operations=[
            SceneEditIntent(operation="add", operation_id="op-1", target="basket"),
            SceneEditIntent(operation="add", operation_id="op-2", target="apple", reference="basket", relation="inside", depends_on=["op-1"]),
        ],
    )
    assert [op.operation_id for op in plan.operations] == ["op-1", "op-2"]


def test_v3_placement_goal_is_distinct_from_selection_relations_but_editor_compatible():
    operation = SceneEditIntent(operation="add", target="apple",
                                placement_goal=PlacementGoal(relation="on", reference="table"))
    assert operation.relation.value == "on"
    assert operation.reference == "table"
    assert operation.placement_goal.reference == "table"


def test_forward_dependency_is_rejected():
    with pytest.raises(ValueError, match="scene_edit_invalid_dependency"):
        SceneEditPlan(
            entities=[{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            operations=[SceneEditIntent(operation="add", operation_id="op-1", target="apple", depends_on=["op-2"])],
        )


def test_reference_catalog_can_be_loaded_from_config(tmp_path):
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"scene_references": [{
        "canonical_id": "workbench", "aliases": ["bench", "工作台"],
        "kind": "support_surface", "allow_default": True,
    }]}, ensure_ascii=False), encoding="utf-8")
    config = BrainConfig(scene_reference_catalog=str(path))
    catalog = config.load_scene_reference_catalog()
    assert catalog.canonical("工作台") == "workbench"
