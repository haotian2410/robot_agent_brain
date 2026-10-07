import pytest
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.asset_resolver import AssetResolver
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from test_application_artifacts import Provider, robot


def test_add_layout_is_seeded_and_repeatable(tmp_path):
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="添加两个苹果",
                     scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=2, quantity_mode='all')], operations=[SceneEditIntent(operation='add', target="target")]))
    positions = []
    for index, seed in enumerate((0,0,17)):
        app = BrainApplication(BrainConfig(provider="replay", seed=seed, output_dir=str(tmp_path / str(index))), provider=Provider(turn))
        report = app.handle(turn.instruction)
        assert report.run_status == "success", report
        scene = app.get_session(report.session_id).scene
        apples = [o for o in scene.objects if o.semantic_name == "apple"]
        positions.append([o.transform.position for o in apples])
        assert any(abs(apples[0].transform.position[i]-apples[1].transform.position[i]) >= .08+app.defaults.clearance_m for i in (0,1))
    assert positions[0] == positions[1] and positions[0] != positions[2]


def test_work_area_must_fit_actual_support_geometry():
    config = BrainConfig()
    defaults = config.load_defaults().model_copy(update={"workspace_max":(2,2)})
    with pytest.raises(ValueError, match="bootstrap_workspace_outside_support"):
        SceneBootstrapper(config.load_assets(), defaults).prepare(robot(), scene_id="s")


def test_exact_asset_name_does_not_bypass_category_constraint():
    resolver = AssetResolver(BrainConfig().load_assets())
    with pytest.raises(ValueError, match="asset_category_mismatch"):
        resolver.resolve(TaskEntity(entity_id="a", semantic_name="apple", category="container"))
    assert resolver.resolve(TaskEntity(entity_id="a", semantic_name="苹果", category="水果")).model.asset_id == "demo_apple"


def test_grounding_override_does_not_bypass_category_constraint():
    config = BrainConfig()
    task = robot()
    initial = SceneBootstrapper(config.load_assets(), config.load_defaults()).prepare(task, scene_id="s")
    task.task_intent.entities[0].category = "container"
    with pytest.raises(ValueError, match="grounding_binding_invalid"):
        SceneGrounder().ground(task.task_intent, initial.scene, initial.bindings_for(initial.scene))


def test_generated_category_alias_works_through_full_pipeline(tmp_path):
    turn = robot()
    turn.task_intent.entities[0].category = "水果"
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)), provider=Provider(turn))
    report = app.handle("two apples")
    assert report.run_status == "success", report
    assert "commands" in report.artifacts
