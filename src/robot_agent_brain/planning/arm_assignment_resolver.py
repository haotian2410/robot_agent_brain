"""Deterministic logical allocation, never a reachability assertion."""


def resolve_arms(expanded_task, robot_profile, *, arm_usage="unspecified"):
    objects = {entity.entity_id: entity.scene_object_id for entity in expanded_task.entities}
    operations = expanded_task.operations
    if any(op.arm not in {None, "left", "right"} for op in operations):
        raise ValueError("dual_arm_assignment_required")
    assignments = {}
    # Explicit ownership wins, including over earlier unspecified operations.
    for op in operations:
        actor = objects[op.source or op.target]
        if op.arm is not None:
            if actor in assignments and assignments[actor] != op.arm:
                raise ValueError("capability_unsupported: shared ownership or handover")
            assignments[actor] = op.arm
    result = []
    for op in operations:
        actor = objects[op.source or op.target]
        arm = op.arm or assignments.get(actor)
        if arm is None:
            if arm_usage == "both_required":
                counts = {side: list(assignments.values()).count(side) for side in ("left", "right")}
                arm = min(counts, key=counts.get)
            else:
                arm = robot_profile.default_task_arm
        if arm not in {"left", "right"}:
            raise ValueError("dual_arm_assignment_required")
        assignments[actor] = arm
        result.append(op.model_copy(update={"arm": arm}))
    if arm_usage == "both_required" and {op.arm for op in result} != {"left", "right"}:
        raise ValueError("capability_unsupported: both arms require distinct independently owned objects")
    return expanded_task.model_copy(update={"operations": result})
