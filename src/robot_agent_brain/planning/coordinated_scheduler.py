"""Bounded stage dependencies; no trajectories, sensor claims or model repair."""


def temporal_edges(steps, operations, holds):
    occurrences = {op.operation_id: [] for op in operations}
    actions = {}
    for index, step in enumerate(steps):
        for side in ("left", "right"):
            action = getattr(step.arms, side)
            if action is not None:
                occurrences[action.operation_id].append(index)
                actions[(index, side)] = action
    edges = set()
    for op in operations:
        indices = occurrences[op.operation_id]
        if not indices:
            raise ValueError("dual_schedule_operation_missing")
        edges.update(zip(indices, indices[1:]))
        for dependency in op.depends_on:
            edges.add((occurrences[dependency][-1], indices[0]))
    for hold in holds:
        if hold.kind != "hold_until_operation":
            continue
        holder = next(op for op in operations if op.operation_id == hold.holder_operation)
        if (holder.task_type != "pick_and_place" or holder.source != hold.object_id
                or holder.destination != hold.region_object_id or holder.arm != hold.holder_arm):
            raise ValueError("dual_hold_holder_semantics_mismatch")
        indices = occurrences[hold.holder_operation]
        ready = [i for i in indices if actions[(i, hold.holder_arm)].skill_name == "move"
                 and actions[(i, hold.holder_arm)].parameters.region == hold.region
                 and actions[(i, hold.holder_arm)].parameters.target == hold.region_object_id]
        release = [i for i in indices if actions[(i, hold.holder_arm)].skill_name == "release"
                   and actions[(i, hold.holder_arm)].parameters.target == hold.object_id]
        if len(ready) != 1 or len(release) != 1 or release[0] != indices[-1]:
            raise ValueError("dual_hold_milestone_missing")
        peer = occurrences[hold.while_operation]
        edges.add((ready[0], peer[0]))
        edges.add((peer[-1], release[0]))
    return edges, occurrences


def schedule_stages(steps, operations, holds):
    edges, _ = temporal_edges(steps, operations, holds)
    pending = set(range(len(steps)))
    ordered = []
    while pending:
        ready = [i for i in pending if not any(end == i and start in pending for start, end in edges)]
        if not ready:
            raise ValueError("dual_schedule_dependency_cycle")
        index = min(ready)
        pending.remove(index)
        ordered.append(steps[index].model_copy(update={"step_id": f"stage-{len(ordered)+1}"}))
    return ordered


def validate_stage_order(plan):
    edges, occurrences = temporal_edges(plan.steps, plan.operations, plan.hold_constraints)
    if any(start >= end for start, end in edges):
        raise ValueError("dual_milestone_order_invalid")
    by_id = {op.operation_id: op for op in plan.operations}
    for step in plan.steps:
        if step.arms.left is not None and step.arms.right is not None:
            left, right = (by_id[getattr(step.arms, side).operation_id] for side in ("left", "right"))
            if left.parallel_group is None or left.parallel_group != right.parallel_group:
                raise ValueError("dual_unrequested_parallel")
    for op in plan.operations:
        if op.parallel_required:
            peers = [p for p in plan.operations if p.parallel_group == op.parallel_group]
            if len(peers) != 2 or len({occurrences[p.operation_id][0] for p in peers}) != 1:
                raise ValueError("dual_required_parallel_missing")
