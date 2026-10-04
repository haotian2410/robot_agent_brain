from __future__ import annotations

from ..contracts.turn import BrainTurn, SceneEditIntent, TurnKind, TurnStatus


class TaskDomainPolicy:
    """Apply the public distinction between scene editing and robot actions."""

    def classify(self, turn: BrainTurn, instruction: str) -> BrainTurn:
        if turn.status != TurnStatus.ACCEPTED or turn.turn_kind != TurnKind.ROBOT_TASK or turn.task_intent is None:
            return turn
        text = instruction.casefold()
        has_robot_chain = any(token in text for token in ("抓", "拿起", "夹", "放进", "放到", "释放", "机械臂", "robot", "grasp", "pick"))
        has_scene_phrase = any(token in text for token in ("场景中", "直接修改", "直接移动", "直接旋转"))
        if any(token in text for token in ("增加", "添加", "删除")) and has_robot_chain and any(token in text for token in ("然后", "再", "之后")):
            return BrainTurn(status=TurnStatus.CLARIFICATION_REQUIRED, turn_kind=TurnKind.ROBOT_TASK, instruction=instruction)
        move_only = bool(turn.task_intent.operations) and all(op.task_type.value == "move" for op in turn.task_intent.operations)
        if move_only and not has_robot_chain and not has_scene_phrase:
            operation = turn.task_intent.operations[0]
            entity = next(item for item in turn.task_intent.entities if item.entity_id == (operation.target or operation.source))
            reference = None
            relation = None
            if operation.placement_target and operation.placement_target.kind == "relative_object":
                ref_entity = next((item for item in turn.task_intent.entities if item.entity_id == operation.placement_target.reference), None)
                reference = ref_entity.semantic_name if ref_entity else operation.placement_target.reference
                relation = operation.placement_target.relation
            return turn.model_copy(update={
                "turn_kind": TurnKind.SCENE_EDIT,
                "task_intent": None,
                "scene_edit": SceneEditIntent(
                    operation="move_relative" if reference else "translate",
                    semantic_name=entity.semantic_name,
                    category=entity.category,
                    count=entity.count,
                    direction=operation.motion_direction.value if operation.motion_direction else None,
                    distance_m=operation.distance_m,
                    motion_scale=operation.motion_scale.value if operation.motion_scale else None,
                    reference=reference,
                    relation=relation,
                ),
            })
        if move_only and has_robot_chain and any(token in text for token in ("然后", "再", "之后")):
            return BrainTurn(status=TurnStatus.CLARIFICATION_REQUIRED, turn_kind=TurnKind.ROBOT_TASK, instruction=instruction)
        return turn
