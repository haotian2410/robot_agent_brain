from __future__ import annotations

from ..contracts.grounded_task import GroundedTask
from ..contracts.scene import SceneId
from ..contracts.skill_plan import SkillName, SkillPlan, SkillStep
from ..contracts.task_intent import TaskType


class RecipePlanner:
    SUPPORTED_TASK_TYPES = frozenset({TaskType.LOCATE, TaskType.MOVE, TaskType.GRASP, TaskType.RELEASE,
                                    TaskType.PICK_AND_PLACE, TaskType.PRESS, TaskType.OPEN, TaskType.CLOSE})

    @classmethod
    def supports(cls, task: GroundedTask) -> bool:
        return all(op.task_type in cls.SUPPORTED_TASK_TYPES for op in task.operations)

    def plan(self, task: GroundedTask, held_object: SceneId | None = None) -> SkillPlan:
        steps: list[SkillStep] = []
        current_held = held_object
        bindings = {entity.entity_id: entity.scene_object_id for entity in task.entities}

        def add(operation_id, skill, target=None, reference=None, region=None):
            nonlocal current_held
            if target is not None and target not in bindings:
                raise ValueError("plan_precondition_failed: unknown target")
            object_id = bindings.get(target)
            if skill == SkillName.GRASP:
                if current_held is not None:
                    raise ValueError(f"holding_conflict: gripper already holds {current_held}")
                current_held = object_id
            elif skill == SkillName.RELEASE:
                if current_held != object_id or current_held is None:
                    raise ValueError("plan_precondition_failed: release target is not held")
                current_held = None
            steps.append(SkillStep(
                step_id=f"step-{len(steps) + 1}", operation_id=operation_id,
                skill_name=skill, target_entity=target,
                reference_entity=reference, region=region,
            ))

        for operation in task.operations:
            op = operation.operation_id
            actor = operation.target or operation.source
            if operation.task_type == TaskType.GRASP:
                add(op, SkillName.LOCATE, actor)
                add(op, SkillName.MOVE, actor, region="grasp_region")
                add(op, SkillName.GRASP, actor)
            elif operation.task_type == TaskType.MOVE:
                standalone = current_held is None
                if not standalone and current_held != bindings[actor]:
                    raise ValueError("holding_conflict: move target differs from held object")
                if standalone:
                    add(op, SkillName.LOCATE, actor)
                    add(op, SkillName.MOVE, actor, region="grasp_region")
                    add(op, SkillName.GRASP, actor)
                add(op, SkillName.MOVE, actor)
                if standalone:
                    add(op, SkillName.RELEASE, actor)
            elif operation.task_type == TaskType.PICK_AND_PLACE:
                already_held = current_held is not None and any(e.entity_id == operation.source and e.scene_object_id == current_held for e in task.entities)
                if not already_held:
                    add(op, SkillName.LOCATE, operation.source)
                    add(op, SkillName.MOVE, operation.source, region="grasp_region")
                    add(op, SkillName.GRASP, operation.source)
                add(op, SkillName.LOCATE, operation.destination)
                add(op, SkillName.MOVE, operation.destination, operation.source, "placement_region")
                add(op, SkillName.RELEASE, operation.source, operation.destination, "placement_region")
            elif operation.task_type == TaskType.PRESS:
                add(op, SkillName.LOCATE, actor)
                add(op, SkillName.MOVE, actor, region="button_surface")
                add(op, SkillName.PRESS, actor)
            elif operation.task_type == TaskType.OPEN:
                add(op, SkillName.LOCATE, operation.reference or actor)
                add(op, SkillName.MOVE, operation.reference or actor, region="grasp_region")
                add(op, SkillName.GRASP, operation.reference or actor)
                add(op, SkillName.PULL, actor, operation.reference)
                add(op, SkillName.RELEASE, operation.reference or actor)
            elif operation.task_type == TaskType.CLOSE:
                add(op, SkillName.LOCATE, actor)
                add(op, SkillName.PUSH, actor, operation.reference)
            elif operation.task_type == TaskType.RELEASE:
                add(op, SkillName.RELEASE, actor)
            elif operation.task_type == TaskType.LOCATE:
                add(op, SkillName.LOCATE, actor)
            else:
                raise ValueError("capability_unsupported: " + operation.task_type.value)
        return SkillPlan(steps=steps)
