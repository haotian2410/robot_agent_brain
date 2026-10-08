import pytest
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditPlan, SceneEditIntent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.scene_graph import world_transform
from component_fixtures import demo_bootstrap, named_objects, semantic_names


def prepare(entities, operations):
    config = BrainConfig()
    assets, defaults = config.load_assets(), config.load_defaults()
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="test",
                     scene_edit=SceneEditPlan(entities=entities, operations=operations))
    bootstrap = demo_bootstrap(config)[1].prepare(turn, scene_id=1)
    return turn, bootstrap, SceneEditor(assets), defaults


def test_first_add_objects_created_exactly_once():
    turn, initial, editor, defaults = prepare([
        TaskEntity(entity_id="a", semantic_name="apple", category="fruit", count=2, quantity_mode="all"),
        TaskEntity(entity_id="b", semantic_name="basket", category="container")], [
        SceneEditIntent(operation="add", target="a"), SceneEditIntent(operation="add", target="b")])
    assert len(initial.scene.objects) == 2
    patch = editor.edit(turn.scene_edit, initial.scene, defaults=defaults)
    final = SceneManager(initial.scene).apply_patch(patch)
    assert final.scene_version == 2
    assert len(final.objects) == 5
    assert len(named_objects(final, "apple")) == 2


def test_add_then_move_same_turn_identity():
    turn, initial, editor, defaults = prepare([
        TaskEntity(entity_id="a", semantic_name="apple", category="fruit", dialogue_ref=True)], [
        SceneEditIntent(operation="add", target="a"),
        SceneEditIntent(operation="translate", target="a", direction="right", distance_m=.1)])
    patch = editor.edit(turn.scene_edit, initial.scene, defaults=defaults)
    assert [op.action for op in patch.operations] == ["add_object", "upsert_component", "upsert_component", "upsert_component"]
    added, _, moved, facts = patch.operations
    assert facts.component.properties["support"] == 0
    assert added.object_id_in_scene == moved.object_id_in_scene
    assert moved.component.properties["position"][0] == pytest.approx(added.object.components[0].properties["position"][0] + .1)
    final = SceneManager(initial.scene).apply_patch(patch)
    assert len(final.objects) == 3 and final.scene_version == 2
    outcome = editor.edit_result(turn.scene_edit, initial.scene, defaults=defaults)
    assert outcome.patch == patch
    assert outcome.created_object_ids == outcome.focus_object_ids == [added.object_id_in_scene]
    assert outcome.entity_bindings["a"] == [added.object_id_in_scene]
    assert outcome.deleted_object_ids == []


def test_no_default_context_does_not_guess_add_position():
    turn, initial, editor, _ = prepare([TaskEntity(entity_id="a", semantic_name="apple", category="fruit")],
        [SceneEditIntent(operation="add", target="a")])
    with pytest.raises(ValueError, match="scene_edit_reference_missing"):
        editor.edit(turn.scene_edit, initial.scene)


def test_all_available_add_never_defaults_to_one():
    turn, initial, editor, defaults = prepare([TaskEntity(entity_id="a", semantic_name="apple", category="fruit",
                                                        quantity_mode="all", all_available=True)],
                                             [SceneEditIntent(operation="add", target="a")])
    with pytest.raises(ValueError, match="bootstrap_quantity_unspecified"):
        editor.edit(turn.scene_edit, initial.scene, defaults=defaults)
    defaults.initial_counts["apple"] = 3
    patch = editor.edit(turn.scene_edit, initial.scene, defaults=defaults)
    assert len([op for op in patch.operations if op.action == "add_object"]) == 3
    assert len([op for op in patch.operations if op.action == "upsert_component" and op.component.component_type == "Semantic" and op.component.properties["support"] == 0]) == 3


def test_canonical_reference_add_bootstraps_reference_only():
    config = BrainConfig()
    assets, defaults = config.load_assets(), config.load_defaults()
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="在苹果右边增加香蕉",
        scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='banana', category='fruit', count=1, quantity_mode='single'), dict(entity_id="reference", semantic_name='apple', category="fruit")], operations=[SceneEditIntent(operation='add', relation='right_of', target="target", reference="reference")]))
    initial = demo_bootstrap(config)[1].prepare(turn, scene_id=1)
    assert semantic_names(initial.scene).count("apple") == 1
    assert not bool(named_objects(initial.scene, "banana"))
    patch = SceneEditor(assets).edit(turn.scene_edit, initial.scene, defaults=defaults)
    final = SceneManager(initial.scene).apply_patch(patch)
    assert semantic_names(final).count("banana") == 1
    apple = named_objects(final, "apple")[0]
    banana = named_objects(final, "banana")[0]
    assert world_transform(final, banana.object_id_in_scene).position[0] > world_transform(final, apple.object_id_in_scene).position[0]
