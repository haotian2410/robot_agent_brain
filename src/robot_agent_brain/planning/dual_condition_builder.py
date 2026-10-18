"""One deterministic condition catalogue for Recipe, Qwen and validation.

These are symbolic requirements, not sensor evidence or physical guarantees.
"""
from ..contracts.commands_v3 import CoordinatedStep


def bind_hold_constraints(task):
    from ..contracts.commands_v3 import HoldConstraint
    bindings = {entity.entity_id: entity.scene_object_id for entity in task.entities}
    result = []
    for hold in task.hold_constraints:
        data = hold.model_dump(exclude={"object_entity", "region_entity"})
        data["object_id"] = bindings[hold.object_entity]
        data["region_object_id"] = bindings[hold.region_entity] if hold.region_entity else None
        result.append(HoldConstraint.model_validate(data))
    return result


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
            result.append({"predicate": "at_region", "arm": side,
                           "object_id": p.reference if p.reference is not None else p.target, "region": p.region})
    return result


def required_invariants(plan, index):
    result = []
    for hold in plan.hold_constraints:
        active = [i for i, step in enumerate(plan.steps)
                  if any(cmd is not None and cmd.operation_id == hold.while_operation
                         for cmd in (step.arms.left, step.arms.right))]
        if active and min(active) <= index <= max(active):
            result.append({"predicate": "holding", "arm": hold.holder_arm, "object_id": hold.object_id})
            if hold.region is not None:
                result.append({"predicate": "at_region", "arm": hold.holder_arm,
                               "object_id": hold.region_object_id, "region": hold.region})
    return result


def build_conditions(plan, initial_runtime):
    # Deliberately do not claim initial_runtime proves an unmeasured region.
    stages = []
    for index, step in enumerate(plan.steps):
        data = step.model_dump()
        for key, required in (("preconditions", required_conditions({s: getattr(step.arms, s) for s in ("left", "right")})),
                              ("invariants", required_invariants(plan, index))):
            for condition in required:
                if condition not in data[key]:
                    data[key].append(condition)
        stages.append(CoordinatedStep.model_validate(data))
    return plan.model_copy(update={"steps": stages})


def require_condition_coverage(stage, plan, index):
    for label, required, actual in (
        ("precondition", required_conditions({s: getattr(stage.arms, s) for s in ("left", "right")}), stage.preconditions),
        ("invariant", required_invariants(plan, index), stage.invariants),
    ):
        values = [c.model_dump() for c in actual]
        if any(condition not in values for condition in required):
            raise ValueError("dual_required_" + label + "_missing")
