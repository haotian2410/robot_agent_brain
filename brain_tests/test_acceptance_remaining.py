import json
from pathlib import Path
import pytest
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig, Transform
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneQueryIntent, SceneEditPlan
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.scene.transform_editor import rotate
from test_application_artifacts import Provider, robot
from test_scene_bootstrap import task
from component_fixtures import demo_bootstrap, named_objects
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.scene_graph import world_transform
from robot_agent_brain.scene.geometry import world_bounds
from test_query_scene_continuity import transform


def app_at(path, turn):
    return BrainApplication(BrainConfig(provider="replay", output_dir=str(path)), provider=Provider(turn))


def test_b02_initial_geometry_is_outside_target_container(tmp_path):
    app = app_at(tmp_path, robot())
    report = app.handle("two apples")
    scene = app.get_session(report.session_id).scene
    basket = named_objects(scene, "basket")[0]
    index = SceneIndex(scene)
    bounds = lambda obj: world_bounds(app.assets.resolve(index.metadata_ref(obj.object_id_in_scene)),
                                     world_transform(scene, obj.object_id_in_scene))
    blow, bhigh = bounds(basket)
    for apple in named_objects(scene, "apple"):
        low, high = bounds(apple)
        assert any(high[i] <= blow[i] or bhigh[i] <= low[i] for i in (0, 1))


def test_b08_initial_translation_is_applied_exactly_once(tmp_path):
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="苹果右移十厘米",
        scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single')], operations=[SceneEditIntent(operation='translate', direction='right', distance_m=0.1, target="target")]))
    app = app_at(tmp_path, turn)
    initial = app.bootstrapper.prepare(turn, scene_id=1).scene
    initial_apple = named_objects(initial, "apple")[0]
    report = app.handle(turn.instruction)
    assert report.run_status == "success", report
    final = app.get_session(report.session_id).scene
    apple = named_objects(final, "apple")[0]
    assert world_transform(final, apple.object_id_in_scene).position[0] == pytest.approx(world_transform(initial, initial_apple.object_id_in_scene).position[0]+.1)
    assert final.scene_version == initial.scene_version + 1 and app.provider.count == 1


@pytest.mark.parametrize("payload", ["{broken", '{"schema_version":"99","scene_id":"s"}', '{"components":[]}'])
def test_b12_bad_upload_never_generates_or_calls_model(tmp_path, payload):
    file = tmp_path / "input.json"
    file.write_text(payload)
    app = app_at(tmp_path / "out", robot())
    report = app.handle("two apples", scene_path=file)
    assert report.run_status == "failed" and not report.scene_created
    assert app.provider.count == 0 and "commands" not in report.artifacts
    assert file.read_text() == payload


def test_b14_missing_asset_has_no_commands_or_partial_scene(tmp_path):
    turn = robot()
    turn.task_intent.entities[0].semantic_name = "pear"
    report = app_at(tmp_path, turn).handle("two pears")
    assert report.error.code == "asset_missing" and report.scene_created is False
    assert "commands" not in report.artifacts and "scene_config" not in report.artifacts


def test_b16_insufficient_workspace_never_reduces_count():
    config = BrainConfig()
    defaults = config.load_defaults().model_copy(update={"workspace_min":(0,0),"workspace_max":(.01,.01),"max_attempts":2})
    turn = task()
    with pytest.raises(ValueError, match="bootstrap_layout_failed"):
        bootstrap = demo_bootstrap(config)[1]
        bootstrap.defaults = defaults
        bootstrap.prepare(turn, scene_id=1)
    assert turn.task_intent.entities[0].count == 2


def test_s02_world_local_rotation_differ_and_preserve_other_components():
    original = transform(position=(1,2,3), quaternion_xyzw=(0,0,2**-.5,2**-.5), scale=(2,3,4))
    world = rotate(original, "x", 90, "world").to_local_properties()
    local = rotate(original, "x", 90, "object_local").to_local_properties()
    assert world.quaternion_xyzw != local.quaternion_xyzw
    assert world.position == local.position == original.position
    assert world.scale == pytest.approx(original.scale)
    assert local.scale == pytest.approx(original.scale)
    assert world.quaternion_xyzw == pytest.approx((.5,-.5,.5,.5))
    assert local.quaternion_xyzw == pytest.approx((.5,.5,.5,.5))


@pytest.mark.parametrize("kind", ["position","state"])
def test_q03_query_reads_confirmed_snapshot_without_increment(tmp_path, kind):
    app = app_at(tmp_path, robot())
    first = app.handle("two apples", session_id="query")
    snapshot = app.get_session("query").scene.model_dump()
    app.provider.turn = BrainTurn(status="accepted", turn_kind="scene_query", instruction="query",
                                 scene_query=SceneQueryIntent(query_type=kind, target="apple", entities=[dict(entity_id="apple", semantic_name="apple", category="fruit")]))
    report = app.handle("query", session_id="query")
    assert report.run_status == "success" and report.scene_version == first.scene_version
    assert app.get_session("query").scene.model_dump() == snapshot
    result = json.loads(Path(report.artifacts["query_result"]).read_text())
    assert len(result["positions" if kind == "position" else "states"]) == 2


def test_a02_success_then_model_failure_never_reuses_commands(tmp_path):
    app = app_at(tmp_path, robot())
    first = app.handle("two apples", session_id="same")
    original = Path(first.artifacts["commands"]).read_bytes()
    def fail(request):
        raise RuntimeError("test provider unavailable")
    app.provider.understand_turn = fail
    second = app.handle("again", session_id="same")
    assert second.run_status == "failed" and "commands" not in second.artifacts
    assert second.request_id != first.request_id
    assert Path(first.artifacts["commands"]).read_bytes() == original


def test_candidate_override_cannot_shrink_pool_before_extreme_selection():
    from robot_agent_brain.pipeline import BrainPipeline
    config = BrainConfig()
    turn = task(pool=True)
    initial = demo_bootstrap(config)[1].prepare(turn, scene_id=1)
    bindings = initial.bindings_for(initial.scene)
    apples = named_objects(initial.scene, "apple")
    bindings["a"] = [min(apples, key=lambda o:world_transform(initial.scene, o.object_id_in_scene).position[0]).object_id_in_scene]
    with pytest.raises(ValueError, match="grounding_candidate_pool_count_mismatch"):
        BrainPipeline(None, config.load_assets()).process_turn("r", turn, initial.scene, bindings_override=bindings)
