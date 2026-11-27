"""Deterministic logical allocation, never a reachability assertion."""


def resolve_arms(expanded_task, robot_profile, *, arm_usage="unspecified", runtime=None, audit=None,
                 model_provider=None, scene=None, capture=None):
    objects = {entity.entity_id: entity.scene_object_id for entity in expanded_task.entities}
    operations = expanded_task.operations
    if any(op.arm not in {None, "left", "right"} for op in operations):
        raise ValueError("dual_arm_assignment_required")
    assignments = {}
    reasons = {}
    for op in operations:
        if op.arm is not None:
            assignments[op.operation_id] = op.arm
            reasons[op.operation_id] = "explicit_arm"
    if runtime is not None and (
            set(runtime.arms) != {"left", "right"}
            or any(not state.state_known for state in runtime.arms.values())):
        raise ValueError("robot_runtime_state_unknown")
    model_status = "not_needed"
    unresolved = any(op.operation_id not in assignments for op in operations)
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
                request = ArmAssignmentRequest(scene_id=scene.scene_id, scene_version=scene.scene_version,
                    scene_sub_version=scene.scene_sub_version, scene_digest=digest(scene),
                    arm_labels=labels, frame=frame, both_required=arm_usage == "both_required",
                    initial_held_objects={side: state.holding_object for side, state in runtime.arms.items()},
                    operations=[BoundArmOperation(operation_id=op.operation_id,
                        source=objects[op.source or op.target], destination=objects.get(op.destination),
                        locked_arm=assignments.get(op.operation_id)) for op in operations])
                output = ArmAssignmentOutput.model_validate(model_provider.assign_arms(request))
                model_status = output.status
                if output.status == "assigned":
                    validate_assignment_output(output, operation_ids=[op.operation_id for op in operations],
                        locked_arms={op.operation_id: op.locked_arm for op in request.operations if op.locked_arm},
                        both_required=request.both_required,
                        ordered_operations=[op.operation_id for op in operations])
                    assigned = {item.operation_id: item.arm for item in output.assignments}
                    for op in operations:
                        if op.operation_id not in assignments:
                            assignments[op.operation_id] = assigned[op.operation_id]
                            reasons[op.operation_id] = "visual_assignment"
    result = []
    for op in operations:
        actor = objects[op.source or op.target]
        arm = op.arm or assignments.get(op.operation_id)
        if arm is None:
            if arm_usage == "both_required":
                counts = {side: list(assignments.values()).count(side) for side in ("left", "right")}
                arm = min(counts, key=counts.get)
                reasons[op.operation_id] = "deterministic_balanced_fallback"
            else:
                arm = robot_profile.default_task_arm
                reasons[op.operation_id] = "configured_default_arm"
        if arm not in {"left", "right"}:
            if model_provider is not None:
                raise ValueError("arm_assignment_insufficient_evidence")
            raise ValueError("dual_arm_assignment_required")
        assignments[op.operation_id] = arm
        result.append(op.model_copy(update={"arm": arm}))
        if audit is not None:
            audit.append({"operation_id": op.operation_id, "object_id": actor,
                          "arm": arm, "source": reasons[op.operation_id], "model_status": model_status})
    if arm_usage == "both_required" and {op.arm for op in result} != {"left", "right"}:
        raise ValueError("capability_unsupported: both arms required")
    return expanded_task.model_copy(update={"operations": result})
