"""Build a Commands v4 DAG from already-bound operations.

This module never assigns arms, resolves objects, or performs physical checks.
Those decisions must be made before calling ``build_commands_dag``.
"""
from __future__ import annotations

from ..contracts.commands_dag_v4 import CommandsFileV4, DagCommand, ResourceGroup
from .atomic_operation_ir import AtomicOperationIR
from ..contracts.dual_skill_draft import AtomicSkillDraft


def build_commands_dag(*, request_id, scene_id, scene_version, scene_digest,
                       robot_setup_revision, skill_contract_revision, operations,
                       skill_steps, resource_groups=(), sync_groups=(), hold_constraints=()):
    commands = []
    operations = list(operations)
    operation_ids = [operation.operation_id for operation in operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("commands_v4_duplicate_operation")
    if set(skill_steps) != set(operation_ids):
        raise ValueError("commands_v4_operation_coverage_invalid")
    if any(operation.arm not in {"left", "right"} for operation in operations):
        raise ValueError("commands_v4_arm_assignment_missing")
    previous_by_arm = {}
    last_by_operation = {}
    for operation in operations:
        steps = skill_steps.get(operation.operation_id)
        if not steps:
            raise ValueError("commands_v4_skill_steps_missing")
        for index, step in enumerate(steps):
            step = AtomicSkillDraft.model_validate(step)
            command_id = f"{operation.arm[:1].upper()}-{operation.operation_id}-{index + 1}"
            # Reject model scheduling instead of silently deleting it.
            depends = []
            if index == 0:
                for dependency in getattr(operation, "depends_on", []) or []:
                    if dependency not in last_by_operation:
                        raise ValueError("commands_v4_operation_dependency_missing")
                    depends.append(last_by_operation[dependency])
            if operation.arm in previous_by_arm:
                depends.append(previous_by_arm[operation.arm])
            command = DagCommand(command_id=command_id, operation_id=operation.operation_id,
                                 arm=operation.arm, skill_name=step.skill_name,
                                 parameters=dict(step.parameters),
                                 depends_on=list(dict.fromkeys(depends)))
            commands.append(command)
            previous_by_arm[operation.arm] = command_id
            last_by_operation[operation.operation_id] = command_id
    groups = [ResourceGroup.model_validate(item) if not isinstance(item, ResourceGroup) else item
              for item in resource_groups]
    return CommandsFileV4(request_id=request_id, scene_id=scene_id, scene_version=scene_version,
                          scene_digest=scene_digest, robot_setup_revision=robot_setup_revision,
                          skill_contract_revision=skill_contract_revision,
                          commands=commands, resource_groups=groups,
                          sync_groups=list(sync_groups), hold_constraints=list(hold_constraints))


def build_commands_dag_from_ir(*, request_id, scene_id, scene_version, scene_digest,
                               robot_setup_revision, skill_contract_revision,
                               operations: list[AtomicOperationIR], skill_steps,
                               resource_groups=(), sync_groups=(), hold_constraints=()):
    """Emit v4 from provider-independent IR, preserving explicit dependencies."""
    if any(operation.arm not in {"left", "right"} for operation in operations):
        raise ValueError("commands_v4_arm_assignment_missing")
    return build_commands_dag(
        request_id=request_id, scene_id=scene_id, scene_version=scene_version,
        scene_digest=scene_digest, robot_setup_revision=robot_setup_revision,
        skill_contract_revision=skill_contract_revision, operations=operations,
        skill_steps=skill_steps, resource_groups=resource_groups,
        sync_groups=sync_groups, hold_constraints=hold_constraints)


def build_negotiated_commands_dag(*, skill_contract, draft, operations, **context):
    """Build only against a trusted adapter snapshot; no implicit v3 fallback."""
    from ..contracts.control_skill_contract import ControlSkillContract
    from ..contracts.dual_skill_draft import DualSkillDraft
    contract = ControlSkillContract.model_validate(skill_contract)
    if "4.0" not in contract.supported_protocols:
        raise ValueError("unsupported_protocol_version: commands_dag_v4")
    operations = list(operations)
    steps = DualSkillDraft.model_validate(draft).steps_for(op.operation_id for op in operations)
    commands = build_commands_dag_from_ir(operations=operations, skill_steps=steps,
        skill_contract_revision=contract.revision, **context)
    return contract.validate_commands(commands)
