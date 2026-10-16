"""Validate model stage order and reuse existing per-operation effect checks."""
from ..contracts.commands_v3 import CommandsFileV3, DualCommand, DualOperation, CoordinatedStep
from ..contracts.skill_plan import SkillPlan, SkillStep
from ..models.dual_skill_planning import DualSkillPlanningRequest, DualSkillPlanOutput, dual_context
from .context_builder import operation_valid_roles
from .command_exporter import CommandExporter
from .coordinated_validator import CoordinatedValidator
from .skill_planner_router import PlanningTrace


class DualQwenPlanner:
    def plan(self, request_id, task, scene, profile, revision, runtime, provider, registry, trace):
        if provider is None or not hasattr(provider, "plan_dual"):
            raise ValueError("dual_qwen_planner_not_configured")
        if any(not a.state_known for a in runtime.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        if any(op.task_type.value not in {"locate", "move", "grasp", "release", "pick_and_place"} for op in task.operations):
            raise ValueError("dual_planner_capability_unsupported")
        context = dual_context(task, runtime)
        trace.context = context
        trace.skill_catalog = registry.prompt_catalog()
        trace.model_calls = 1
        raw = provider.plan_dual(DualSkillPlanningRequest(context=context, skill_catalog=trace.skill_catalog))
        trace.raw_output = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
        raw = DualSkillPlanOutput.model_validate(trace.raw_output)
        ops = {op.operation_id: op for op in task.operations}
        gathered = {key: [] for key in ops}
        stage_slots = []
        last_on_arm = {}
        finished = set()
        for stage in raw.stages:
            slots = {}
            for side in ("left", "right"):
                action = getattr(stage, side)
                if action is None:
                    continue
                op = ops.get(action.operation_id)
                if op is None or op.arm != side:
                    raise ValueError("dual_planner_operation_or_arm_mismatch")
                if last_on_arm.get(side) != op.operation_id:
                    if op.operation_id in finished:
                        raise ValueError("dual_planner_same_arm_operation_interleave")
                    if side in last_on_arm:
                        finished.add(last_on_arm[side])
                    last_on_arm[side] = op.operation_id
                roles = operation_valid_roles(op)
                if action.target_role not in roles or action.reference_role is not None and action.reference_role not in roles:
                    raise ValueError("dual_planner_role_invalid")
                step = SkillStep(step_id=f"{op.operation_id}-skill-{len(gathered[op.operation_id])+1}",
                    operation_id=op.operation_id, skill_name=action.skill,
                    target_entity=getattr(op, action.target_role),
                    reference_entity=getattr(op, action.reference_role) if action.reference_role else None, region=action.region)
                slots[side] = (op.operation_id, len(gathered[op.operation_id]))
                gathered[op.operation_id].append(step)
            if len(slots) == 2:
                left, right = (ops[slots[s][0]] for s in ("left", "right"))
                if left.parallel_group is None or left.parallel_group != right.parallel_group:
                    raise ValueError("dual_planner_unrequested_parallel")
            stage_slots.append(slots)
        held = {side: a.holding_object for side, a in runtime.arms.items()}
        concrete = {}
        operations = []
        bindings = {e.entity_id: e.scene_object_ids for e in task.entities}
        for op in task.operations:
            if not gathered[op.operation_id]:
                raise ValueError("dual_planner_operation_missing")
            single = task.model_copy(update={"operations": [op]})
            wire = CommandExporter(profile.setup.profile_id).export(request_id, single,
                SkillPlan(steps=gathered[op.operation_id]), scene, held_object=held[op.arm])
            for i, cmd in enumerate(wire.commands):
                data = cmd.model_dump()
                data["command_id"] = f"{op.operation_id}-{op.arm}-command-{i+1}"
                concrete[(op.operation_id, i)] = DualCommand.model_validate(data)
                if cmd.skill_name == "grasp":
                    held[op.arm] = cmd.parameters.target
                elif cmd.skill_name == "release":
                    held[op.arm] = None
            operations.append(DualOperation(**wire.operations[0].model_dump(), task_type=op.task_type.value,
                arm=op.arm, source=bindings[op.source][0] if op.source else None,
                destination=bindings[op.destination][0] if op.destination else None,
                target=bindings[op.target][0] if op.target else None,
                depends_on=op.depends_on, parallel_group=op.parallel_group, parallel_required=op.parallel_required))
        for op in task.operations:
            if op.parallel_required:
                peers = [other for other in task.operations if other.parallel_group == op.parallel_group]
                starts = {next(i for i, slots in enumerate(stage_slots) if any(k[0] == other.operation_id for k in slots.values())) for other in peers}
                if len(peers) != 2 or len(starts) != 1:
                    raise ValueError("dual_planner_required_parallel_missing")
        stages = []
        for i, slots in enumerate(stage_slots):
            arms = {side: concrete[slots[side]] if side in slots else None for side in ("left", "right")}
            stages.append(CoordinatedStep(step_id=f"stage-{i+1}", semantic_intent="; ".join(ops[key[0]].task_type.value for key in slots.values()), arms=arms,
                                          preconditions=required_conditions(arms)))
        commands = CommandsFileV3(request_id=request_id, scene_id=scene.scene_id, scene_version=scene.scene_version,
            robot_setup=profile.setup, robot_setup_revision=revision, operations=operations, steps=stages)
        CoordinatedValidator().validate(commands, runtime)
        trace.normalized = commands
        trace.validation = {"valid": True, "scope": "symbolic_not_physical"}
        return commands


def required_conditions(arms):
    result = []
    for side, cmd in arms.items():
        if cmd is None:
            continue
        p, skill = cmd.parameters, cmd.skill_name.value
        if skill == "move" and p.region is not None:
            result.append({"predicate": "located", "object_id": p.target})
            if p.reference is not None:
                result.append({"predicate": "holding", "arm": side, "object_id": p.reference})
        if skill == "grasp":
            result.extend([{"predicate": "gripper_empty", "arm": side},
                           {"predicate": "at_region", "arm": side, "object_id": p.target, "region": "grasp_region"}])
        if skill == "release" or skill == "move" and p.region is None:
            result.append({"predicate": "holding", "arm": side, "object_id": p.target})
        if skill == "release" and p.region is not None:
            result.append({"predicate": "at_region", "arm": side, "object_id": p.reference if p.reference is not None else p.target, "region": p.region})
    return result
