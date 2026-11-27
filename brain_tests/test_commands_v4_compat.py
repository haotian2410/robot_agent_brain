import pytest

from robot_agent_brain.contracts.commands import canonical_commands, parse_commands
from robot_agent_brain.contracts.commands_dag_v4 import CommandsFileV4
from robot_agent_brain.session.brain_session import BrainSession


def commands():
    return CommandsFileV4(schema_version="4.1", request_id="r", scene_id=1, scene_version=1,
        scene_digest="a" * 64, robot_setup_revision=0, skill_contract_revision="s",
        commands=[{"command_id": "c", "operation_id": "o", "arm": "left", "skill_name": "pick"}])


def test_v4_can_replay_without_flattening_graph():
    original = commands()
    restored = parse_commands(canonical_commands(original))
    assert isinstance(restored, CommandsFileV4)
    assert restored == original


def test_unnegotiated_v4_rejected_before_dispatch_state_changes():
    session = BrainSession(None, None, None)
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        session.mark_dispatched(commands())
    assert session.pending_commands is None
    assert session.pending_execution_request is None
    assert not session.dispatched_requests
