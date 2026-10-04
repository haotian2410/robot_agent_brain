from __future__ import annotations

from ..contracts.grounded_task import GroundedTask
from ..contracts.skill_plan import SkillName, SkillPlan, SkillStep
from ..contracts.task_intent import TaskType


class RecipePlanner:
    def plan(self, task: GroundedTask, held_object: str | None = None) -> SkillPlan:
        steps: list[SkillStep] = []
        current_held = held_object

        def add(operation_id, skill, target=None, reference=None, region=None):
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
                add(op, SkillName.LOCATE, actor)
                add(op, SkillName.MOVE, actor, region="grasp_region")
                add(op, SkillName.GRASP, actor)
                add(op, SkillName.MOVE, actor)
                add(op, SkillName.RELEASE, actor)
            elif operation.task_type == TaskType.PICK_AND_PLACE:
                already_held = current_held is not None and any(e.entity_id == operation.source and e.scene_object_id == current_held for e in task.entities)
                if not already_held:
                    add(op, SkillName.LOCATE, operation.source)
                    add(op, SkillName.MOVE, operation.source, region="grasp_region")
                    add(op, SkillName.GRASP, operation.source)
                    current_held = next((e.scene_object_id for e in task.entities if e.entity_id == operation.source), operation.source)
                add(op, SkillName.LOCATE, operation.destination)
                add(op, SkillName.MOVE, operation.destination, operation.source, "placement_region")
                add(op, SkillName.RELEASE, operation.source, operation.destination, "placement_region")
                current_held = None
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
            else:
                add(op, SkillName.LOCATE, actor)
        return SkillPlan(steps=steps)
