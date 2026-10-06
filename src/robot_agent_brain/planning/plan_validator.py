"""Independent semantic checks, not robot kinematics or execution simulation."""
from collections import Counter

from ..contracts.grounded_task import GroundedTask
from ..contracts.skill_plan import SkillPlan


class PlanValidator:
    def validate(self, task, plan, scene, *, held_object=None):
        task = GroundedTask.model_validate(task.model_dump())
        plan = SkillPlan.model_validate(plan.model_dump())
        def require(condition, reason):
            if not condition:
                raise ValueError("plan_precondition_failed: " + reason)

        require((task.scene_id, task.scene_version) == (scene.scene_id, scene.scene_version), "scene mismatch")
        objects = {o.scene_object_id for o in scene.objects}
        bindings = {e.entity_id:e.scene_object_id for e in task.entities}
        require(all(len(e.scene_object_ids) == 1 and e.scene_object_id in objects for e in task.entities), "concrete existing instances required")
        require(held_object is None or held_object in objects, "unknown held object")
        operations = {op.operation_id:op for op in task.operations}
        require(len(operations) == len(task.operations), "duplicate operation ID")
        require(len({s.step_id for s in plan.steps}) == len(plan.steps), "duplicate step ID")
        require({s.operation_id for s in plan.steps} == set(operations), "operation coverage mismatch")
        order = {op.operation_id:i for i, op in enumerate(task.operations)}
        indices = [order[s.operation_id] for s in plan.steps]
        require(indices == sorted(indices), "operation order mismatch")
        held = held_object
        completed = set()
        for op in task.operations:
            require(set(op.depends_on) <= completed, "unmet operation dependencies")
            actor = op.source or op.target
            require(actor in bindings, "missing actor")
            for role in (op.target, op.source, op.destination, op.reference):
                require(role is None or role in bindings, "unknown operation role")
            kind = op.task_type.value
            require(kind in {"grasp", "move", "pick_and_place", "release", "locate", "press", "open", "close"}, "unsupported task " + kind)
            steps = [s for s in plan.steps if s.operation_id == op.operation_id]
            counts = Counter(s.skill_name.value for s in steps)
            initial_held = held
            allowed = {actor, op.reference} - {None}
            if kind == "pick_and_place":
                allowed.add(op.destination)
                require(op.placement_target is not None and op.placement_target.reference == op.destination,
                        "placement reference differs from destination")
                require(bindings[actor] != bindings[op.destination], "self placement")
            located, reached = set(), None
            for step in steps:
                require(step.target_entity in allowed and step.target_entity in bindings, "step target role mismatch")
                require(step.reference_entity is None or step.reference_entity in allowed, "step reference role mismatch")
                target = bindings[step.target_entity]
                skill = step.skill_name.value
                if skill == "locate":
                    located.add(target)
                elif skill == "move":
                    if step.region:
                        require(target in located, "move requires located target")
                        require(step.region in {"grasp_region", "placement_region", "button_surface"}, "unsupported region")
                        if step.region == "placement_region":
                            require(kind == "pick_and_place" and step.target_entity == op.destination
                                    and step.reference_entity == actor and held == bindings[actor], "placement move roles/holding mismatch")
                        else:
                            require(held is None, "approach with occupied gripper")
                            approach_actor = op.reference or actor if kind == "open" else actor
                            require(step.target_entity == approach_actor, "approach actor mismatch")
                        reached = (target, step.region)
                    else:
                        require(kind == "move" and step.target_entity == actor and held == target,
                                "direction move requires matching held object")
                        require(op.distance_m is not None and op.motion_direction is not None, "missing displacement")
                elif skill == "grasp":
                    require(held is None and reached == (target, "grasp_region"), "grasp precondition")
                    held = target
                elif skill == "release":
                    require(held == target, "release requires matching held object")
                    if kind == "pick_and_place":
                        require(step.target_entity == actor and step.reference_entity == op.destination
                                and step.region == "placement_region"
                                and reached == (bindings[op.destination], "placement_region"), "release placement mismatch")
                    held = None
                elif skill == "press":
                    require(kind == "press" and held is None and reached == (target, "button_surface"), "press precondition")
                elif skill == "pull":
                    require(kind == "open" and held == bindings[op.reference or actor], "pull precondition")
                elif skill == "push":
                    require(kind == "close" and held is None and target in located, "push precondition")
            expected = {
                "grasp":{"grasp":1}, "release":{"release":1}, "locate":{},
                "press":{"press":1}, "open":{"grasp":1,"pull":1,"release":1}, "close":{"push":1},
                "move":({"grasp":1,"release":1} if initial_held is None else {}),
                "pick_and_place":({"release":1} if initial_held == bindings[actor] else {"grasp":1,"release":1}),
            }[kind]
            require({k:v for k,v in counts.items() if k not in {"move","locate"}} == expected, "missing or extra effect")
            move_count = {"grasp":1, "release":0, "locate":0, "press":1, "open":1, "close":0,
                          "move":2 if initial_held is None else 1,
                          "pick_and_place":1 if initial_held == bindings[actor] else 2}[kind]
            require(counts["move"] == move_count, "missing or extra move")
            if kind == "move":
                require(sum(s.skill_name == "move" and s.region is None for s in steps) == 1, "direction move coverage")
                require(held == (None if initial_held is None else bindings[actor]), "move final holding")
            elif kind in {"pick_and_place","release","open"}:
                require(held is None, "final release missing")
            elif kind == "grasp":
                require(held == bindings[actor], "grasp actor mismatch")
            completed.add(op.operation_id)
        return plan
