from types import SimpleNamespace

import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.release_policy import ReleasePolicy
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.session.brain_session import BrainSession


def test_v02_policy_is_closed_by_default():
    policy = ReleasePolicy()
    assert policy.version == "v0.2"
    with pytest.raises(ValueError, match="capability_unsupported"):
        policy.deny_dynamic_platform()
    with pytest.raises(ValueError, match="capability_unsupported"):
        policy.deny_runtime_robot_setup()


def test_v02_rejects_open_release_flags():
    with pytest.raises(ValueError, match="release_policy_v02_capability_must_be_disabled"):
        ReleasePolicy(dynamic_platform_rebind=True)


def test_application_config_contains_closed_policy():
    assert BrainConfig().release_policy.dynamic_platform_rebind is False


def test_session_rejects_robot_switch_before_assembly_write():
    class Platform:
        def load_scene(self, scene, **kwargs):
            raise AssertionError("platform write must not be reached")

    session = BrainSession(None, SimpleNamespace(), Platform(), release_policy=ReleasePolicy())
    turn = BrainTurn.model_validate({
        "status": "accepted", "turn_kind": "robot_config", "instruction": "换成 Piper",
        "robot_asset_switch": {"robot_asset": "piper", "gripper_asset": None,
                                "camera_asset": None, "profile_id": None},
    })
    with pytest.raises(ValueError, match="capability_unsupported"):
        session.check_turn(turn)


def test_loaded_session_cannot_be_replaced_by_second_import(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.contracts.scene import SceneConfig

    class Provider:
        def understand_turn(self, request):
            raise AssertionError("understanding is not reached")

    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1,
                        scene_sub_version=0, scene_name="fixture", objects=[])
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(scene.model_dump_json(), encoding="utf-8")
    second.write_text(scene.model_copy(update={"scene_id": 2}).model_dump_json(), encoding="utf-8")
    app = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path / "out")), provider=Provider())
    app.load_scene("s", first)
    with pytest.raises(ValueError, match="capability_unsupported"):
        app.load_scene("s", second)


def test_rejected_platform_request_does_not_commit_same_turn_import(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.contracts.scene import SceneConfig

    class Provider:
        def understand_turn(self, request):
            return BrainTurn.model_validate({
                "status": "accepted", "turn_kind": "robot_config",
                "instruction": request.instruction,
                "robot_setup_request": {"mode": "dual"},
            })

    scene = SceneConfig(scene_schema_version=1, scene_id=3, scene_version=1,
                        scene_sub_version=0, scene_name="fixture", objects=[])
    path = tmp_path / "input.json"
    path.write_text(scene.model_dump_json(), encoding="utf-8")
    app = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path / "out")), provider=Provider())
    report = app.handle("换成双臂", session_id="s", scene_path=path)
    assert report.run_status == "blocked"
    assert report.error.code == "capability_unsupported"
    assert app.get_session("s").scene is None
