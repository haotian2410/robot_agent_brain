from __future__ import annotations

from ..contracts.grounded_task import GroundedTask
from ..contracts.task_intent import Direction, TaskType
from ..models.motion_policy import MotionPolicy
from ..ports.asset_catalog import AssetCatalogPort


class MotionScaleResolver:
    def __init__(self, assets: AssetCatalogPort, policy: MotionPolicy | None = None):
        self.assets = assets
        self.policy = policy or MotionPolicy()

    def resolve(self, task: GroundedTask) -> GroundedTask:
        entities = {item.entity_id: item for item in task.entities}
        operations = []
        for operation in task.operations:
            if operation.task_type != TaskType.MOVE or operation.motion_scale is None or operation.distance_m is not None:
                operations.append(operation)
                continue
            actor = entities.get(operation.target or operation.source)
            if actor is None:
                raise ValueError(f"motion_scale_grounding_missing: {operation.operation_id}")
            try:
                model = self.assets.get_model_property(actor.asset_id)
            except LookupError as exc:
                raise ValueError(
                    f"motion_scale_geometry_missing: operation={operation.operation_id} asset={actor.asset_id}"
                ) from exc
            axis = {
                Direction.LEFT: 0, Direction.RIGHT: 0,
                Direction.FRONT: 1, Direction.BACK: 1,
                Direction.UP: 2, Direction.DOWN: 2,
            }[operation.motion_direction]
            distance = model.dimensions_m[axis] * self.policy.scale_factor(operation.motion_scale)
            operations.append(operation.model_copy(update={"distance_m": distance, "motion_scale": None}))
        return task.model_copy(update={"operations": operations})

