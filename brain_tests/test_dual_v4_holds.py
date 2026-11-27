"""Old hold scheduling tests are replaced by explicit metadata rejection."""
import pytest
from robot_agent_brain.contracts.control_skill_contract import ControlSkillContract
from test_control_skill_contract import contract
from test_commands_sequence_v41 import payload
from robot_agent_brain.contracts.commands_dag_v4 import CommandsFileV4


@pytest.mark.parametrize("field", ["supports_hold", "supports_sync", "supports_resources"])
@pytest.mark.parametrize("value", [True, False])
def test_controller_scheduling_flags_are_not_brain_planning_capabilities(field, value):
    data = contract()
    data[field] = value
    with pytest.raises(ValueError):
        ControlSkillContract.model_validate(data)


def test_old_hold_envelope_is_not_silently_discarded():
    data = payload()
    data["hold_constraints"] = []
    with pytest.raises(ValueError, match="commands_v41_shared_metadata_forbidden"):
        CommandsFileV4.model_validate(data)
