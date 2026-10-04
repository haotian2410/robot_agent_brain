from ..contracts.task_intent import TaskType


def validate_operation_contract(operation):
    prefix = "task_semantic_invalid: "
    if operation.task_type in {TaskType.GRASP, TaskType.RELEASE, TaskType.PRESS, TaskType.LOCATE, TaskType.SEARCH} and not operation.target:
        raise ValueError(prefix + f"{operation.task_type.value} requires target")
    if operation.task_type == TaskType.MOVE:
        if not (operation.target or operation.source):
            raise ValueError(prefix + "move requires target or source")
        if not operation.motion_direction:
            raise ValueError(prefix + "move requires motion_direction")
        if (operation.distance_m is None) == (operation.motion_scale is None):
            raise ValueError(prefix + "move requires exactly one of distance_m or motion_scale")
    if operation.task_type == TaskType.PICK_AND_PLACE:
        if not operation.source or not operation.destination or not operation.placement_target:
            raise ValueError(prefix + "pick_and_place requires source, destination and placement_target")
        placement = operation.placement_target
        if not (placement.kind == "free_space" and placement.reference is None) and placement.reference != operation.destination:
            raise ValueError(prefix + "placement_target reference must match destination")
        if operation.source == operation.destination:
            raise ValueError(prefix + "source and destination must differ")
    if operation.task_type != TaskType.MOVE and any(v is not None for v in (operation.motion_direction, operation.distance_m, operation.motion_scale)):
        raise ValueError(prefix + "motion parameters require move operation")
    if operation.task_type in {TaskType.OPEN, TaskType.CLOSE}:
        if not operation.target or not operation.reference:
            raise ValueError(prefix + f"{operation.task_type.value} requires target and reference")
        if operation.target == operation.reference:
            raise ValueError(prefix + "open/close target and reference must differ")
