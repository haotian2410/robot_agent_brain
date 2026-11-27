import pytest
from robot_agent_brain.contracts.composite_turn import CompositeTask
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.contracts.task_intent import TaskIntent
from robot_agent_brain.web.protocol import digest
from test_dual_v4_pipeline import setup as dual_setup
from test_layout_transaction import setup as layout_setup


def prepared(target="apple"):
    session = dual_setup()
    table_scene, spec, editor = layout_setup()
    scene = session.scene
    scene.objects = [obj for obj in scene.objects if obj.object_id_in_scene in {2, 3}]
    scene.objects.extend(table_scene.objects)
    session.initialize_scene(scene)
    session.bind_imported_profile(session.robot_profiles.profiles["fixture_only"])
    session.pipeline.scene_editor = editor
    spec = spec.model_copy(update={"pattern": spec.pattern.model_copy(update={"rows": 1, "cols": 1}),
                                   "items": spec.items.model_copy(update={"requested_count": 1})})
    layout = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="摆一个苹果",
                       arrangement_spec=spec)
    robot = BrainTurn(status="accepted", turn_kind="robot_task", instruction="左臂抓苹果",
        task_intent=TaskIntent(instruction="左臂抓苹果",
            entities=[{"entity_id": "apple", "semantic_name": target, "category": "fruit"}],
            operations=[{"operation_id": "op-1", "task_type": "grasp", "target": "apple", "arm": "left"}]))
    return session, CompositeTask(instruction="摆一个苹果再让左臂抓", phases=[layout, robot])


def test_dual_layout_then_plan_uses_new_ids_version_and_mode():
    session, task = prepared()
    results = session.process_composite_turn("dual-layout", task)
    created = results[0].layout_resolution.instance_ids
    commands = results[1].commands
    assert commands.schema_version == "4.1"
    assert commands.scene_version == session.scene.scene_version
    assert commands.scene_digest == digest(session.scene)
    assert commands.commands[0].parameters["source"] == created[0]
    assert commands.commands[0].arm == "left"
    phases = session.composite_turn_records[-1]["phases"]
    assert phases[0]["scene_digest_after"] == phases[1]["scene_digest_before"]
    assert [phase["mode"] for phase in phases] == ["dual", "dual"]
    assert phases[0]["prompt_route"] is None
    assert phases[1]["prompt_route"] == "dual_atomic"


def test_dual_robot_binding_failure_keeps_layout_and_exports_no_commands():
    session, task = prepared("banana")
    before = session.scene.scene_version
    with pytest.raises(Exception) as error:
        session.process_composite_turn("missing-target", task)
    assert str(error.value).startswith("grounding_missing:")
    assert session.scene.scene_version == before + 1
    assert not session.exported_commands
    assert not session.robot_mode_lock.locked and session.robot_mode_lock.mode == "dual"
    phases = session.composite_turn_records[-1]["phases"]
    assert [phase["status"] for phase in phases] == ["committed", "failed"]
    assert phases[0]["scene_digest_after"] == digest(session.scene)
    assert phases[1]["scene_digest_before"] == phases[1]["scene_digest_after"]


def test_composite_robot_phase_missing_requested_profile_preserves_unlocked_layout():
    from robot_agent_brain.contracts.robot_setup import RobotSetupRequest
    session, task = prepared()
    task.phases[1].robot_setup_request = RobotSetupRequest(mode="single")
    before = session.scene.scene_version
    with pytest.raises(ValueError, match="robot_setup_profile_not_registered"):
        session.process_composite_turn("mode-drift", task)
    assert session.scene.scene_version == before + 1
    assert session.robot_mode_lock.mode == "dual"
    assert not session.exported_commands
    phases = session.composite_turn_records[-1]["phases"]
    assert phases[1]["error_code"] == "robot_setup_profile_not_registered"
    assert [phase["status"] for phase in phases] == ["committed", "failed"]
