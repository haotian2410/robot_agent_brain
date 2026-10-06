import pytest
from robot_agent_brain.contracts.grounded_task import GroundedTask, GroundedEntity
from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.planning.task_expander import TaskExpander


def pair_task(count=2):
    return GroundedTask(instruction="把两个苹果分别放入两个盒子", scene_id="s", scene_version=0,
        entities=[GroundedEntity(entity_id=name, semantic_name=name, category=category, asset_id=name,
                    scene_object_id=name+"_1", scene_object_ids=[f"{name}_{i+1}" for i in range(n)])
                  for name, category, n in (("apple", "fruit", 2), ("box", "container", count))],
        operations=[Operation(operation_id="op-1", task_type="pick_and_place", source="apple", destination="box",
                    assignment_mode="pairwise", placement_target={"kind":"container_interior", "reference":"box", "relation":"inside"})])


def test_one_collection_operation_preserves_every_pair():
    expanded = TaskExpander().expand(pair_task())
    assert [(op.source, op.destination) for op in expanded.operations] == [("apple__01","box__01"),("apple__02","box__02")]
    assert [op.placement_target.reference for op in expanded.operations] == ["box__01", "box__02"]
    assert expanded.operations[1].depends_on == [expanded.operations[0].operation_id]


def test_incomplete_distributed_pairing_does_not_drop_an_apple():
    with pytest.raises(ValueError, match="pairwise_coverage_mismatch"):
        TaskExpander().expand(pair_task(count=1))


def test_unequal_collections_never_truncate_to_shortest():
    with pytest.raises(ValueError, match="cardinality_mismatch"):
        TaskExpander().expand(pair_task(count=3))
