import pytest
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditPlan, SceneEditIntent
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation
from robot_agent_brain.contracts.spatial import SpatialRelation
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.pipeline import BrainPipeline


def setup():
    config = BrainConfig()
    assets = config.load_assets()
    return assets, SceneBootstrapper(assets, config.load_defaults())


def task(pool=False, source="apple", destination="basket"):
    entities = [TaskEntity(entity_id="a", semantic_name=source, category="fruit", count=2,
                           quantity_mode="candidate_pool" if pool else "all"),
                TaskEntity(entity_id="b", semantic_name=destination, category="container")]
    return BrainTurn(status="accepted", turn_kind="robot_task", instruction="test", task_intent=TaskIntent(
        instruction="test", entities=entities,
        operations=[Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="b",
                              placement_target={"kind":"container_interior", "reference":"b", "relation":"inside"})],
        spatial_relations=[SpatialRelation(subject="a", relation="rightmost")] if pool else []))


@pytest.mark.parametrize("pool", [False, True])
def test_generated_quantity_goal_separation_and_candidate_selection(pool):
    assets, bootstrap = setup()
    turn = task(pool)
    result = bootstrap.prepare(turn, scene_id="s")
    apples = [o for o in result.scene.objects if o.semantic_name == "apple"]
    assert len(apples) == 2
    assert all("container_membership" not in o.properties for o in apples)
    class NoProvider:
        def understand_turn(self, request):
            raise AssertionError("must not understand again")
    output = BrainPipeline(NoProvider(), assets).process_turn("r", turn, result.scene,
                                                            bindings_override=result.bindings_for(result.scene))
    grasps = [c for c in output.commands.commands if c.skill_name == "grasp"]
    assert len(grasps) == (1 if pool else 2)
    if pool:
        assert grasps[0].parameters.target == max(apples, key=lambda o:o.transform.position[0]).scene_object_id
    assert output.commands.scene_id == result.scene.scene_id
    assert output.commands.scene_version == result.scene.scene_version
    assert bootstrap.prepare(turn, scene_id="s").scene == result.scene


def test_generation_is_not_fixed_apple_scene():
    _, bootstrap = setup()
    result = bootstrap.prepare(task(source="banana", destination="box"), scene_id="s")
    assert [o.semantic_name for o in result.scene.objects] == ["table", "banana", "banana", "box"]


def test_add_targets_not_precreated_and_reference_exists():
    _, bootstrap = setup()
    plan = SceneEditPlan(entities=[TaskEntity(entity_id="a", semantic_name="apple", category="fruit"),
                                   TaskEntity(entity_id="b", semantic_name="banana", category="fruit")],
                         operations=[SceneEditIntent(operation="add", target="b", reference="a", relation="right_of")])
    result = bootstrap.prepare(BrainTurn(status="accepted", turn_kind="scene_edit", instruction="add", scene_edit=plan), scene_id="s")
    assert [o.semantic_name for o in result.scene.objects] == ["table", "apple"]


def test_unknown_all_count_and_unsupported_initial_relation():
    _, bootstrap = setup()
    turn = task()
    turn.task_intent.entities[0].all_available = True
    with pytest.raises(ValueError, match="bootstrap_quantity_unspecified"):
        bootstrap.prepare(turn, scene_id="s")
    turn.task_intent.entities[0].all_available = False
    turn.task_intent.spatial_relations = [SpatialRelation(subject="a", reference="b", relation="inside")]
    with pytest.raises(ValueError, match="bootstrap_relation_unsupported"):
        bootstrap.prepare(turn, scene_id="s")


def test_pure_remove_does_not_create_objects():
    _, bootstrap = setup()
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="remove",
                     scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single')], operations=[SceneEditIntent(operation='remove', target="target")]))
    with pytest.raises(ValueError, match="scene_required"):
        bootstrap.prepare(turn, scene_id="s")


def test_generation_bindings_do_not_bypass_color():
    assets, bootstrap = setup()
    turn = task()
    result = bootstrap.prepare(turn, scene_id="s")
    turn.task_intent.entities[0].color = "red"
    with pytest.raises(ValueError, match="grounding_binding_invalid"):
        BrainPipeline(None, assets).process_turn("r", turn, result.scene, bindings_override=result.bindings_for(result.scene))
