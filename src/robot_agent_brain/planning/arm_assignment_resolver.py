"""Deterministic logical allocation, never a reachability assertion."""


def resolve_arms(expanded_task, robot_profile, *, arm_usage="unspecified", runtime=None, audit=None,
                 model_provider=None, scene=None, capture=None):
    objects = {entity.entity_id: entity.scene_object_id for entity in expanded_task.entities}
    operations = expanded_task.operations
    if any(op.arm not in {None, "left", "right"} for op in operations):
        raise ValueError("dual_arm_assignment_required")
    assignments = {}
    reasons = {}
    # Explicit ownership wins, including over earlier unspecified operations.
    for op in operations:
        actor = objects[op.source or op.target]
        if op.arm is not None:
            if actor in assignments and assignments[actor] != op.arm:
                raise ValueError("capability_unsupported: shared ownership or handover")
            assignments[actor] = op.arm
            reasons[actor] = "explicit_arm"
    # A held object is an identity constraint, not an opportunity to guess a
    # handover. Reject contradictory explicit requests before any skill plan.
    if runtime is not None:
        if set(runtime.arms) != {"left", "right"} or any(not state.state_known for state in runtime.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        held_owners = {}
        for side, state in runtime.arms.items():
            actor = state.holding_object
            if actor is None:
                continue
            if actor in held_owners:
                raise ValueError("arm_assignment_duplicate_holder")
            held_owners[actor] = side
            if actor in assignments and assignments[actor] != side:
                raise ValueError("arm_assignment_held_object_conflict")
            assignments[actor] = side
            reasons.setdefault(actor, "held_object")
    # Connect all explicit same-arm groups, including transitive connections
    # through an actor that appears in more than one group. Identity continuity
    # and user constraints share the same lock, regardless of model/fallback.
    actors = {objects[op.source or op.target] for op in operations}
    parent = {actor: actor for actor in actors}
    def root(actor):
        while parent[actor] != actor:
            parent[actor] = parent[parent[actor]]
            actor = parent[actor]
        return actor
    first_by_group = {}
    for op in operations:
        actor = objects[op.source or op.target]
        if op.same_arm_group is not None:
            first = first_by_group.setdefault(op.same_arm_group, actor)
            parent[root(actor)] = root(first)
    components = {}
    for actor in actors:
        components.setdefault(root(actor), set()).add(actor)
    def lock_component(actor, arm, source):
        for member in components[root(actor)]:
            if member in assignments and assignments[member] != arm:
                raise ValueError("arm_assignment_same_arm_conflict")
            if member not in assignments:
                assignments[member] = arm
                reasons[member] = source if member == actor else "same_arm_constraint"
    for actor in actors:
        if actor in assignments:
            lock_component(actor, assignments[actor], reasons[actor])
    model_status = "not_needed"
    unresolved = any(objects[op.source or op.target] not in assignments for op in operations)
    if unresolved:
        model_status = "visual_unavailable"
        if model_provider is not None and hasattr(model_provider, "assign_arms") and capture is not None:
            from ..models.arm_assignment import ArmAssignmentRequest, BoundArmOperation
            from .arm_assignment import ArmAssignmentOutput, validate_assignment_output
            from ..web.protocol import digest
            if scene is None or runtime is None:
                raise ValueError("arm_assignment_scene_runtime_required")
            frame = capture()
            if (frame.scene_id, frame.scene_version, frame.scene_sub_version) != (
                    scene.scene_id, scene.scene_version, scene.scene_sub_version):
                raise ValueError("arm_assignment_frame_scene_mismatch")
            boxes = [box.scene_object_id for box in frame.instance_boxes]
            known = {obj.object_id_in_scene for obj in scene.objects}
            if len(boxes) != len(set(boxes)) or not set(boxes) <= known:
                raise ValueError("arm_assignment_frame_instance_invalid")
            labels = {side: binding.robot_object_id for side, binding in robot_profile.setup.arms.items()}
            required = set(labels.values()) | {objects[op.source or op.target] for op in operations}
            if frame.rgb and required <= set(boxes):
                groups = {}
                for op in operations:
                    groups.setdefault(root(objects[op.source or op.target]), []).append(op.operation_id)
                request = ArmAssignmentRequest(scene_id=scene.scene_id, scene_version=scene.scene_version,
                    scene_sub_version=scene.scene_sub_version, scene_digest=digest(scene),
                    arm_labels=labels, frame=frame, both_required=arm_usage == "both_required",
                    same_arm_groups=list(groups.values()),
                    initial_held_objects={side: state.holding_object for side, state in runtime.arms.items()},
                    operations=[BoundArmOperation(operation_id=op.operation_id,
                        source=objects[op.source or op.target], destination=objects.get(op.destination),
                        locked_arm=assignments.get(objects[op.source or op.target])) for op in operations])
                output = ArmAssignmentOutput.model_validate(model_provider.assign_arms(request))
                model_status = output.status
                if output.status == "assigned":
                    validate_assignment_output(output, operation_ids=[op.operation_id for op in operations],
                        locked_arms={op.operation_id: op.locked_arm for op in request.operations if op.locked_arm},
                        both_required=request.both_required, same_arm_groups=request.same_arm_groups,
                        ordered_operations=[op.operation_id for op in operations])
                    assigned = {item.operation_id: item.arm for item in output.assignments}
                    for op in operations:
                        actor = objects[op.source or op.target]
                        if actor not in assignments:
                            lock_component(actor, assigned[op.operation_id], "visual_assignment")
    result = []
    for op in operations:
        actor = objects[op.source or op.target]
        arm = op.arm or assignments.get(actor)
        if arm is None:
            if arm_usage == "both_required":
                counts = {side: list(assignments.values()).count(side) for side in ("left", "right")}
                arm = min(counts, key=counts.get)
                reasons[actor] = "deterministic_balanced_fallback"
            else:
                arm = robot_profile.default_task_arm
                reasons[actor] = "configured_default_arm"
        if arm not in {"left", "right"}:
            if model_provider is not None:
                raise ValueError("arm_assignment_insufficient_evidence")
            raise ValueError("dual_arm_assignment_required")
        lock_component(actor, arm, reasons[actor])
        result.append(op.model_copy(update={"arm": arm}))
        if audit is not None:
            audit.append({"operation_id": op.operation_id, "object_id": actor,
                          "arm": arm, "source": reasons[actor], "model_status": model_status})
    if arm_usage == "both_required" and {op.arm for op in result} != {"left", "right"}:
        raise ValueError("capability_unsupported: both arms require distinct independently owned objects")
    return expanded_task.model_copy(update={"operations": result})
