import pytest
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditPlan, SceneEditIntent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager


def prepare(entities, operations):
    config = BrainConfig()
    assets, defaults = config.load_assets(), config.load_defaults()
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="test",
                     scene_edit=SceneEditPlan(entities=entities, operations=operations))
    bootstrap = SceneBootstrapper(assets, defaults).prepare(turn, scene_id="s")
    return turn, bootstrap, SceneEditor(assets), defaults


def test_first_add_objects_created_exactly_once():
    turn, initial, editor, defaults = prepare([
        TaskEntity(entity_id="a", semantic_name="apple", category="fruit", count=2, quantity_mode="all", color="red"),
        TaskEntity(entity_id="b", semantic_name="basket", category="container")], [
        SceneEditIntent(operation="add", target="a"), SceneEditIntent(operation="add", target="b")])
    assert len(initial.scene.objects) == 1
    patch = editor.edit(turn.scene_edit, initial.scene, defaults=defaults)
    final = SceneManager(initial.scene).apply_patch(patch)
    assert final.scene_version == 1
    assert len(final.objects) == 4
    assert len([o for o in final.objects if o.semantic_name == "apple" and o.properties["color"] == "red"]) == 2


def test_add_then_move_same_turn_identity():
    turn, initial, editor, defaults = prepare([
        TaskEntity(entity_id="a", semantic_name="apple", category="fruit", dialogue_ref=True)], [
        SceneEditIntent(operation="add", target="a"),
        SceneEditIntent(operation="translate", target="a", direction="right", distance_m=.1)])
    patch = editor.edit(turn.scene_edit, initial.scene, defaults=defaults)
    assert len(patch.operations) == 2
    added, moved = patch.operations
    assert added.scene_object_id == moved.scene_object_id
    assert moved.transform.position[0] == pytest.approx(added.object.transform.position[0] + .1)
    final = SceneManager(initial.scene).apply_patch(patch)
    assert len(final.objects) == 2 and final.scene_version == 1
    outcome = editor.edit_result(turn.scene_edit, initial.scene, defaults=defaults)
    assert outcome.patch == patch
    assert outcome.created_object_ids == outcome.focus_object_ids == [added.scene_object_id]
    assert outcome.entity_bindings["a"] == [added.scene_object_id]
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
    assert len(patch.operations) == 3


def test_legacy_reference_add_bootstraps_reference_only():
    config = BrainConfig()
    assets, defaults = config.load_assets(), config.load_defaults()
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="在苹果右边增加香蕉",
        scene_edit=SceneEditIntent(operation="add", semantic_name="banana", category="fruit", reference="apple", relation="right_of"))
    initial = SceneBootstrapper(assets, defaults).prepare(turn, scene_id="s")
    assert [o.semantic_name for o in initial.scene.objects].count("apple") == 1
    assert not any(o.semantic_name == "banana" for o in initial.scene.objects)
    patch = SceneEditor(assets).edit(turn.scene_edit, initial.scene, defaults=defaults)
    final = SceneManager(initial.scene).apply_patch(patch)
    assert [o.semantic_name for o in final.objects].count("banana") == 1
    apple = next(o for o in final.objects if o.semantic_name == "apple")
    banana = next(o for o in final.objects if o.semantic_name == "banana")
    assert banana.transform.position[0] > apple.transform.position[0]
