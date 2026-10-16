"""Deterministic grasp/place/move recipes for explicitly bound dual arms.

No reachability-based arm allocation and no Control execution. Callers must
resolve deployment capabilities before dispatching the resulting v3 file.
"""
from itertools import zip_longest

from ..contracts.commands_v3 import CommandsFileV3, DualCommand, DualOperation, CoordinatedStep, ArmSlots
from .recipe_planner import RecipePlanner
from .command_exporter import CommandExporter
from .coordinated_validator import CoordinatedValidator


class DualArmRecipePlanner:
    SUPPORTED = {"locate", "grasp", "release", "move", "pick_and_place"}

    def plan(self, request_id, task, scene, setup, revision, runtime):
        if setup.mode != "dual":
            raise ValueError("dual_recipe_requires_dual_setup")
        if (task.scene_id, task.scene_version) != (scene.scene_id, scene.scene_version):
            raise ValueError("command_export_scene_mismatch")
        if set(runtime.arms) != {"left", "right"} or any(not a.state_known for a in runtime.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        if any(op.arm not in {"left", "right"} for op in task.operations):
            raise ValueError("dual_arm_assignment_required")
        if any(op.task_type.value not in self.SUPPORTED for op in task.operations):
            raise ValueError("dual_recipe_capability_unsupported")
        if any(len(e.scene_object_ids) != 1 for e in task.entities):
            raise ValueError("command_export_requires_concrete_entity")
        bindings = {e.entity_id: e.scene_object_ids for e in task.entities}
        held = {side: arm.holding_object for side, arm in runtime.arms.items()}
        blocks = []
        for op in task.operations:
            if op.parallel_group is not None and blocks and blocks[-1][0].parallel_group == op.parallel_group:
                blocks[-1].append(op)
            else:
                blocks.append([op])
        stages, operations = [], []
        for block in blocks:
            if len({op.arm for op in block}) != len(block):
                raise ValueError("dual_parallel_arm_conflict")
            if any(op.parallel_required for op in block) and len(block) != 2:
                raise ValueError("dual_parallel_peer_missing")
            sequences = {}
            for op in block:
                single_task = task.model_copy(update={"operations": [op]})
                recipe = RecipePlanner().plan(single_task, held_object=held[op.arm])
                # Reuse the existing per-operation semantic and geometry gates.
                wire = CommandExporter(robot=setup.profile_id).export(request_id, single_task, recipe, scene,
                                                                      held_object=held[op.arm])
                seq = []
                for index, command in enumerate(wire.commands, 1):
                    data = command.model_dump()
                    data.update(command_id=f"{op.operation_id}-{op.arm}-command-{index}",
                                source_skill_step_id=f"{op.operation_id}-{op.arm}-skill-{index}")
                    seq.append(DualCommand.model_validate(data))
                    if command.skill_name.value == "grasp":
                        held[op.arm] = command.parameters.target
                    elif command.skill_name.value == "release":
                        held[op.arm] = None
                sequences[op.arm] = seq
                operations.append(DualOperation(
                    **wire.operations[0].model_dump(), task_type=op.task_type.value, arm=op.arm,
                    source=bindings[op.source][0] if op.source else None,
                    destination=bindings[op.destination][0] if op.destination else None,
                    target=bindings[op.target][0] if op.target else None,
                    depends_on=op.depends_on, parallel_group=op.parallel_group,
                    parallel_required=op.parallel_required))
            for left, right in zip_longest(sequences.get("left", []), sequences.get("right", [])):
                conditions = []
                for side, command in (("left", left), ("right", right)):
                    if command is None:
                        continue
                    p, skill = command.parameters, command.skill_name.value
                    if skill == "move" and p.region is not None:
                        conditions.append({"predicate": "located", "object_id": p.target})
                        if p.reference is not None:
                            conditions.append({"predicate": "holding", "arm": side, "object_id": p.reference})
                    if skill == "grasp":
                        conditions.extend([{"predicate": "gripper_empty", "arm": side},
                            {"predicate": "at_region", "arm": side, "object_id": p.target, "region": "grasp_region"}])
                    if skill == "release" or (skill == "move" and p.region is None):
                        conditions.append({"predicate": "holding", "arm": side, "object_id": p.target})
                    if skill == "release" and p.region is not None:
                        conditions.append({"predicate": "at_region", "arm": side,
                                           "object_id": p.reference if p.reference is not None else p.target,
                                           "region": p.region})
                stages.append(CoordinatedStep(step_id=f"stage-{len(stages)+1}", semantic_intent="; ".join(o.semantic_intent for o in operations[-len(block):]),
                                              arms=ArmSlots(left=left, right=right), preconditions=conditions))
        result = CommandsFileV3(request_id=request_id, scene_id=scene.scene_id, scene_version=scene.scene_version,
                                robot_setup_revision=revision, robot_setup=setup, operations=operations, steps=stages)
        CoordinatedValidator().validate(result, runtime)
        return result
