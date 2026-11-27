"""Compatibility entry points for 4.1 sequence construction (not 4.0 replay)."""
from .dual_arm_sequence import build_commands_sequence, build_explicit_dependency_edges

build_commands_dag = build_commands_sequence
build_commands_dag_from_ir = build_commands_sequence


def build_negotiated_commands_dag(*, skill_contract, draft, operations, **context):
    from ..contracts.control_skill_contract import ControlSkillContract
    from ..contracts.dual_skill_draft import DualSkillDraft
    contract = ControlSkillContract.model_validate(skill_contract)
    if "4.1" not in contract.supported_protocols:
        raise ValueError("unsupported_protocol_version: dual_arm_sequence_4.1")
    operations = list(operations)
    steps = DualSkillDraft.model_validate(draft).steps_for(op.operation_id for op in operations)
    commands = build_commands_sequence(operations=operations, skill_steps=steps,
        skill_contract_revision=contract.revision, **context)
    return contract.validate_commands(commands)
