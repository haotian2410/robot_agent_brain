"""4.1 sequence construction: explicit semantic edges and per-arm order only."""
from ..contracts.commands_sequence_v41 import CommandsFileV41, SequenceCommand
from ..contracts.dual_skill_draft import AtomicSkillDraft


def build_explicit_dependency_edges(operations, commands_by_operation):
    """Only convert operation.depends_on; never infer physical scheduling."""
    edges = {}
    for operation in operations:
        first = commands_by_operation[operation.operation_id][0].command_id
        dependencies = operation.depends_on
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("commands_v41_dependency_reference_invalid")
        edges[first] = []
        for dependency in dependencies:
            if dependency == operation.operation_id or dependency not in commands_by_operation:
                raise ValueError("commands_v41_dependency_reference_invalid")
            edges[first].append(commands_by_operation[dependency][-1].command_id)
    return edges


def build_commands_sequence(*, operations, skill_steps, request_id, scene_id,
                           scene_version, scene_digest, robot_setup_revision,
                           skill_contract_revision):
    operations = list(operations)
    ids = [operation.operation_id for operation in operations]
    if not ids or len(set(ids)) != len(ids) or set(skill_steps) != set(ids):
        raise ValueError("commands_v41_operation_coverage_invalid")
    commands, by_operation, previous_by_arm = [], {}, {}
    for operation in operations:
        if operation.arm not in {"left", "right"}:
            raise ValueError("commands_v41_arm_assignment_missing")
        steps = skill_steps[operation.operation_id]
        if not steps:
            raise ValueError("commands_v41_operation_coverage_invalid")
        chain = []
        for index, raw in enumerate(steps, 1):
            step = AtomicSkillDraft.model_validate(raw)
            previous = previous_by_arm.get(operation.arm)
            command = SequenceCommand(
                command_id=f"{operation.arm[0].upper()}-{operation.operation_id}-{index}",
                operation_id=operation.operation_id, arm=operation.arm,
                skill_name=step.skill_name, parameters=step.parameters,
                depends_on=[previous] if previous is not None else [])
            commands.append(command)
            chain.append(command)
            previous_by_arm[operation.arm] = command.command_id
        by_operation[operation.operation_id] = chain
    edges = build_explicit_dependency_edges(operations, by_operation)
    for command in commands:
        command.depends_on = list(dict.fromkeys(command.depends_on + edges.get(command.command_id, [])))
    return CommandsFileV41(
        request_id=request_id, scene_id=scene_id, scene_version=scene_version,
        scene_digest=scene_digest, robot_setup_revision=robot_setup_revision,
        skill_contract_revision=skill_contract_revision, commands=commands)
