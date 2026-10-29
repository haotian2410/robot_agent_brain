from __future__ import annotations

from ..contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan, TurnKind, TurnStatus
from ..contracts.task_intent import Operation, TaskIntent
from .robot_interactions import RobotInteractionLexicon
from .domain_policy_registry import DomainPolicyRegistry


class TaskDomainPolicy:
    """Validate the model's domain; explicit robot > explicit scene > action semantics."""

    def __init__(self, registry=None):
        self.registry = registry or DomainPolicyRegistry()

    def classify(self, turn: BrainTurn, instruction: str) -> BrainTurn:
        if turn.status != TurnStatus.ACCEPTED:
            return turn
        text = instruction.casefold()
        if any(token in text for token in ("倒水", "倾倒", "pour water", "pouring water")):
            return BrainTurn(status="unsupported_task", turn_kind="unsupported_task", instruction=instruction)
        explicit_robot = (turn.robot_setup_request is not None
                          or bool(turn.task_intent and any(op.arm is not None for op in turn.task_intent.operations))
                          or any(token in text for token in ("用机械臂", "让机械臂", "用机器人", "让机器人", "using the robot", "左臂", "右臂", "双臂")))
        explicit_scene = any(token in text for token in ("直接修改", "直接移动", "直接旋转", "编辑场景", "修改场景"))
        interaction = RobotInteractionLexicon.matches(text)
        if any(token in text for token in ("增加", "添加", "删除")) and interaction:
            return self._clarify(instruction)
        if turn.turn_kind == TurnKind.SCENE_EDIT:
            from .motion_evidence import normalize_scene_motion
            edits = normalize_scene_motion(instruction, turn.scene_edit)
            turn = turn.model_copy(update={"scene_edit": edits})
            plan = edits
            if explicit_robot or any(op.explicit_robot for op in plan.operations):
                # A scene-edit payload has no typed per-operation arm/time fields.
                # Only a single unambiguous arm can be recovered safely.
                sides = {side for side, words in (("left", ("左臂", "left arm")), ("right", ("右臂", "right arm")))
                         if any(word in text for word in words)}
                if (plan.scene_basis == "original" or "双臂" in text or "both arms" in text
                        or len(sides) > 1 or any(word in text for word in ("同时", "期间", "simultaneously"))):
                    return self._clarify(instruction)
                if any(op.operation != "translate" or op.reference for op in plan.operations):
                    return self._clarify(instruction)
                entities = list(plan.entities)
                operations = []
                for index, edit in enumerate(plan.operations, 1):
                    target = edit.target
                    operations.append(Operation(operation_id=f"op-{index}", task_type="move", target=target,
                                                arm=next(iter(sides), None),
                                                motion_direction=edit.direction, distance_m=edit.distance_m,
                                                motion_scale=edit.motion_scale))
                return BrainTurn(status="accepted", turn_kind="robot_task", instruction=instruction,
                                 robot_setup_request=turn.robot_setup_request,
                                 task_intent=TaskIntent(instruction=instruction, entities=entities,
                                                        operations=operations, spatial_relations=plan.relations))
            # The understanding model has already selected the scene-edit
            # domain and supplied a validated edit payload.  Words such as
            # “放置/移动” also occur in ordinary scene editing (for example,
            # “在桌面上放置一个篮子”), so do not downgrade an explicit
            # scene_edit solely because the interaction lexicon matched.  An
            # explicit robot/arm request is still handled above and remains a
            # separate, safety-gated path.
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
    def __init__(self, registry=None):
        self.registry = registry or DomainPolicyRegistry()
