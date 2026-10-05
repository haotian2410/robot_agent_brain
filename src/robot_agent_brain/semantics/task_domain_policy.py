from __future__ import annotations

from ..contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan, TurnKind, TurnStatus
from ..contracts.task_intent import Operation, TaskIntent, TaskEntity


class TaskDomainPolicy:
    """Validate the model's domain; explicit robot > explicit scene > action semantics."""

    def classify(self, turn: BrainTurn, instruction: str) -> BrainTurn:
        if turn.status != TurnStatus.ACCEPTED:
            return turn
        text = instruction.casefold()
        explicit_robot = any(token in text for token in ("用机械臂", "让机械臂", "用机器人", "让机器人", "using the robot"))
        explicit_scene = any(token in text for token in ("直接修改", "直接移动", "直接旋转", "编辑场景", "修改场景"))
        interaction = any(token in text for token in ("抓", "拿起", "夹住", "放进", "放到", "释放", "放下", "grasp", "pick"))
        if any(token in text for token in ("增加", "添加", "删除")) and interaction:
            return self._clarify(instruction)
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            edits = turn.scene_edit
            plan = edits if isinstance(edits, SceneEditPlan) else SceneEditPlan(operations=[edits])
            if explicit_robot or any(op.explicit_robot for op in plan.operations):
                if any(op.operation != "translate" or op.reference for op in plan.operations):
                    return self._clarify(instruction)
                entities = list(plan.entities)
                operations = []
                for index, edit in enumerate(plan.operations, 1):
                    target = edit.target
                    if target is None:
                        target = f"edit_object_{index}"
                        entities.append(TaskEntity(entity_id=target, semantic_name=edit.semantic_name,
                                                   category=edit.category, count=edit.count,
                                                   quantity_mode="all" if edit.count > 1 else "single"))
                    operations.append(Operation(operation_id=f"op-{index}", task_type="move", target=target,
                                                motion_direction=edit.direction, distance_m=edit.distance_m,
                                                motion_scale=edit.motion_scale))
                return BrainTurn(status="accepted", turn_kind="robot_task", instruction=instruction,
                                 task_intent=TaskIntent(instruction=instruction, entities=entities,
                                                        operations=operations, spatial_relations=plan.relations))
            if interaction and not explicit_scene:
                return self._clarify(instruction)
            return turn
        if turn.turn_kind != TurnKind.ROBOT_TASK or turn.task_intent is None:
            return turn
        task = turn.task_intent
        if explicit_robot or (interaction and not explicit_scene):
            return turn
        if not task.operations or any(op.task_type != "move" for op in task.operations):
            return self._clarify(instruction) if explicit_scene else turn
        from ..models.task_understanding import normalize_motion_language
        task = normalize_motion_language(task.model_copy(update={"instruction": instruction}))
        edits = []
        for operation in task.operations:
            placement = operation.placement_target
            relative = placement is not None and placement.kind == "relative_object"
            edits.append(SceneEditIntent(
                operation="move_relative" if relative else "translate",
                target=operation.target or operation.source,
                direction=operation.motion_direction, distance_m=operation.distance_m,
                motion_scale=operation.motion_scale,
                reference=placement.reference if relative else None,
                relation=placement.relation if relative else None,
            ))
        return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=instruction,
                         scene_edit=SceneEditPlan(entities=task.entities, relations=task.spatial_relations,
                                                  operations=edits))

    @staticmethod
    def _clarify(instruction):
        return BrainTurn(status="clarification_required", turn_kind="scene_edit", instruction=instruction)
