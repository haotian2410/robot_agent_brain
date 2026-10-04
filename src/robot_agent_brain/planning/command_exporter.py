from __future__ import annotations

from ..contracts.commands import Command, CommandOperation, CommandsFile
from ..contracts.grounded_task import GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.skill_plan import SkillName, SkillPlan
from ..contracts.task_intent import TaskType


class CommandExporter:
    """Translate semantic skill steps to commands v2 without physical compilation."""

    def export(self, request_id: str, task: GroundedTask, plan: SkillPlan, scene: SceneConfig) -> CommandsFile:
        bindings = {item.entity_id: item.scene_object_ids for item in task.entities}
        if any(len(ids) != 1 for ids in bindings.values()):
            raise ValueError("command_export_requires_concrete_entity")
        if (task.scene_id, task.scene_version) != (scene.scene_id, scene.scene_version):
            raise ValueError("command_export_scene_mismatch")
        if len({s.step_id for s in plan.steps}) != len(plan.steps):
            raise ValueError("command_export_duplicate_skill_step")
        operations_by_id = {item.operation_id: item for item in task.operations}
        if {s.operation_id for s in plan.steps} != set(operations_by_id):
            raise ValueError("command_export_operation_coverage_mismatch")
        command_operations = [CommandOperation(
            operation_id=item.operation_id,
            semantic_intent=self._semantic_intent(item, bindings),
            placement_target=self._bind_placement(item.placement_target, bindings),
        ) for item in task.operations]
        commands = []
        for index, step in enumerate(plan.steps, start=1):
            operation = operations_by_id[step.operation_id]
            parameters = {}
            if step.target_entity:
                targets = bindings[step.target_entity]
                if len(targets) != 1:
                    raise ValueError("command_export_requires_concrete_entity")
                parameters["target"] = targets[0]
            if step.reference_entity:
                references = bindings[step.reference_entity]
                if len(references) != 1:
                    raise ValueError("command_export_requires_concrete_entity")
                parameters["reference"] = references[0]
            if step.region:
                parameters["region"] = step.region
            if step.skill_name == SkillName.MOVE and operation.task_type == TaskType.MOVE and step.region is None:
                parameters["motion_direction"] = operation.motion_direction.value
                parameters["distance_m"] = operation.distance_m
            commands.append(Command(
                command_id=f"command-{index:03d}",
                source_skill_step_id=step.step_id,
                operation_id=step.operation_id,
                skill_name=step.skill_name.value,
                parameters=parameters,
            ))
        return CommandsFile(
            request_id=request_id,
            scene_id=scene.scene_id,
            scene_version=scene.scene_version,
            robot=scene.robot or "unspecified",
            operations=command_operations,
            commands=commands,
        )

    @staticmethod
    def _bind_placement(placement, bindings):
        if placement is None:
            return None
        reference_values = bindings.get(placement.reference, [placement.reference])
        reference = reference_values[0]
        return placement.model_copy(update={"reference": reference})

    @staticmethod
    def _semantic_intent(operation, bindings):
        actor = operation.source or operation.target
        actor_values = bindings.get(actor, [actor])
        actor_id = actor_values[0]
        if operation.task_type == TaskType.PICK_AND_PLACE:
            destination = bindings[operation.destination][0]
            return f"place {actor_id} relative to {destination}"
        if operation.task_type == TaskType.MOVE:
            return f"move {actor_id} {operation.motion_direction.value} {operation.distance_m}m"
        return f"{operation.task_type.value} {actor_id}"
