import pytest
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
from robot_agent_brain.contracts.turn import BrainTurn, SessionControlIntent
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation
from robot_agent_brain.contracts.commands import ExecutionFeedback, CommandFeedback
from test_component_runtime import object_


def session():
    scene = SceneConfig(scene_schema_version=1, scene_version=0, scene_id=1, scene_name="s",
                        objects=[object_(0, "apple", metadata_ref="$DEMO_LIBRARY/2")])
    return BrainSession(scene, BrainPipeline(None, BrainConfig().load_assets()), MockScenePlatform())


def turn():
    return BrainTurn(status="accepted", turn_kind="robot_task", instruction="抓苹果", task_intent=TaskIntent(
        instruction="抓苹果", entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")],
        operations=[Operation(operation_id="op-1", task_type="grasp", target="apple")]))


def feedback(commands, status="success"):
    return ExecutionFeedback(request_id=commands.request_id, status=status, holding_object=0,
        commands=[CommandFeedback(command_id=c.command_id, status="success") for c in commands.commands])


def test_exports_never_mark_pending_or_change_confirmed_state():
    value = session()
    before = value.scene.model_dump()
    first = value.process_turn("r1", turn())
    second = value.process_turn("r2", turn())
    assert first.commands is not None and second.commands is not None
    assert value.pending_execution_request is None and value.holding_object is None
    assert value.scene.model_dump() == before
    assert value.last_exported_request == "r2"


def test_dispatch_blocks_overwrite_and_scene_switch():
    value = session()
    commands = value.process_turn("r", turn()).commands
    value.mark_dispatched(commands)
    with pytest.raises(ValueError, match="execution_pending"):
        value.process_turn("next", turn())
    with pytest.raises(ValueError, match="execution_pending"):
        value.initialize_scene(value.scene)
    with pytest.raises(ValueError, match="execution_pending"):
        value.mark_dispatched(commands)


def test_feedback_requires_dispatch_and_then_refresh():
    value = session()
    commands = value.process_turn("r", turn()).commands
    with pytest.raises(ValueError, match="stale_or_unknown"):
        value.apply_execution_feedback(feedback(commands))
    value.mark_dispatched(commands)
    bad = feedback(commands).model_copy(update={"request_id":"unknown"})
    with pytest.raises(ValueError):
        value.apply_execution_feedback(bad)
    assert value.holding_object is None
    value.apply_execution_feedback(feedback(commands, "partial"), feedback_source="simulated")
    assert value.sync_state == "unknown" and value.pending_execution_request is None
    assert value.holding_object == 0 and value.last_feedback_source == "simulated"
    with pytest.raises(ValueError, match="scene_sync_unknown"):
        value.process_turn("next", turn())


def test_confirmed_snapshot_restores_sync_without_predicting_pose():
    value = session()
    commands = value.process_turn("r", turn()).commands
    value.mark_dispatched(commands)
    confirmed = value.scene.model_copy(update={"scene_version": 1})
    value.apply_execution_feedback(feedback(commands), confirmed_scene=confirmed)
    assert value.scene == confirmed and value.sync_state == "synchronized"


def test_empty_session_control_no_scene_and_close_while_paused():
    value = BrainSession(None, BrainPipeline(None, BrainConfig().load_assets()), MockScenePlatform())
    for action in ("pause", "close"):
        result = value.process_turn(action, BrainTurn(status="accepted", turn_kind="session_control",
            instruction=action, session_control=SessionControlIntent(action=action)))
        assert result.session_action.action == action
        assert value.scene is None


@pytest.mark.parametrize("invalid", ["duplicate", "foreign", "incomplete", "holding", "old_snapshot"])
def test_invalid_feedback_is_transactional(invalid):
    value = session()
    commands = value.process_turn("r", turn()).commands
    value.mark_dispatched(commands)
    incoming = feedback(commands)
    snapshot = value.scene.model_copy(update={"scene_version":1})
    if invalid == "duplicate":
        incoming.commands.append(incoming.commands[0])
    elif invalid == "foreign":
        incoming.commands[0].command_id = "not-declared"
    elif invalid == "incomplete":
        incoming.commands.pop()
    elif invalid == "holding":
        incoming.holding_object = 999
    else:
        snapshot.scene_version = 0
    before = value.scene.model_dump()
    with pytest.raises(ValueError):
        value.apply_execution_feedback(incoming, confirmed_scene=snapshot)
    assert value.pending_execution_request == "r" and value.holding_object is None
    assert value.sync_state == "synchronized" and value.scene.model_dump() == before
