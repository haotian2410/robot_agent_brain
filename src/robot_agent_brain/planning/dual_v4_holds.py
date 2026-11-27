"""Resolve logical hold intervals from registered effects, never skill names."""
from ..contracts.commands_dag_v4 import CommandsFileV4, HoldConstraintV4


def apply_hold_constraints(commands, task, runtime, contract):
    if not task.hold_constraints:
        return commands
    if not contract.supports_hold:
        raise ValueError("control_dag_feature_unsupported: hold_constraints")
    bindings = {entity.entity_id: entity.scene_object_id for entity in task.entities}
    operations = {operation.operation_id: operation for operation in task.operations}
    op_order = {operation.operation_id: index for index, operation in enumerate(task.operations)}
    chains = {key: [c for c in commands.commands if c.operation_id == key] for key in operations}
    payload = commands.model_dump(mode="json")
    by_id = {c["command_id"]: c for c in payload["commands"]}
    holds = []

    def resulting_hold(chain, held):
        for command in chain:
            effect = contract.skills[command.skill_name].holding_effect
            if effect is None:
                raise ValueError("control_skill_holding_effect_missing: " + command.skill_name)
            if effect.action == "acquire":
                value = command.parameters.get(effect.object_parameter)
                if type(value) is not int or value < 0:
                    raise ValueError("commands_v4_hold_acquisition_identity_invalid")
                if held is not None and held != value:
                    raise ValueError("commands_v4_hold_occupied_arm")
                held = value
            elif effect.action == "release":
                held = None
        return held

    def edge(command_id, predecessor):
        dependencies = by_id[command_id]["depends_on"]
        if predecessor not in dependencies:
            dependencies.append(predecessor)

    for requirement in task.hold_constraints:
        side = requirement.holder_arm
        object_id = bindings.get(requirement.object_entity)
        other = operations.get(requirement.while_operation)
        if object_id is None or other is None or other.arm == side:
            raise ValueError("commands_v4_hold_binding_invalid")
        region_id = bindings.get(requirement.region_entity) if requirement.region_entity else None
        if requirement.region_entity and region_id is None:
            raise ValueError("commands_v4_hold_region_missing")
        held = runtime.arms[side].holding_object
        anchor = None
        if requirement.holder_operation:
            holder = operations.get(requirement.holder_operation)
            if holder is None or holder.arm != side or op_order[holder.operation_id] >= op_order[other.operation_id]:
                raise ValueError("commands_v4_hold_holder_operation_invalid")
            candidates = [op for op in task.operations if op.arm == side
                          and op_order[op.operation_id] <= op_order[holder.operation_id]]
        else:
            candidates = [op for op in task.operations if op.arm == side
                          and op_order[op.operation_id] < op_order[other.operation_id]]
        for operation in candidates:
            held = resulting_hold(chains[operation.operation_id], held)
            anchor = chains[operation.operation_id][-1].command_id
        if held != object_id:
            raise ValueError("commands_v4_hold_not_established")
        first, last = chains[other.operation_id][0], chains[other.operation_id][-1]
        # Do not admit an implicit handover disguised as ordinary acquisition.
        for command in chains[other.operation_id]:
            effect = contract.skills[command.skill_name].holding_effect
            if effect is None:
                raise ValueError("control_skill_holding_effect_missing: " + command.skill_name)
            if effect.action == "acquire" and command.parameters.get(effect.object_parameter) == object_id:
                raise ValueError("commands_v4_hold_conflicting_acquisition")
        if anchor:
            edge(first.command_id, anchor)
        holder_chain = [command for command in commands.commands if command.arm == side]
        next_index = next((i + 1 for i, command in enumerate(holder_chain) if command.command_id == anchor), 0)
        if next_index < len(holder_chain):
            edge(holder_chain[next_index].command_id, last.command_id)
        holds.append(HoldConstraintV4(object_id=object_id, holder_arm=side,
            after_command_id=anchor, until_command_id=last.command_id,
            region_object_id=region_id, region=requirement.region))
    payload["hold_constraints"] = [hold.model_dump(mode="json") for hold in holds]
    # Cycles (including explicit user ordering that conflicts with holding)
    # remain errors; do not delete dependencies to make the plan executable.
    return CommandsFileV4.model_validate(payload)
