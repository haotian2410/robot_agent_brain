"""Shared semantic state transitions; no recipe-shape or physical checks."""
from ..contracts.grounded_task import GroundedTask
from ..contracts.skill_plan import SkillPlan
from ..skills.registry import REGISTRY


class PlanValidator:
    def validate(self, task, plan, scene=None, *, held_object=None):
        task = GroundedTask.model_validate(task.model_dump())
        plan = SkillPlan.model_validate(plan.model_dump())
        def require(condition, reason):
            if not condition:
                raise ValueError("plan_precondition_failed: " + reason)

        bindings = {e.entity_id: e.scene_object_id for e in task.entities}
        require(all(len(e.scene_object_ids) == 1 for e in task.entities), "concrete instances required")
        if scene is not None:
            require((task.scene_id, task.scene_version) == (scene.scene_id, scene.scene_version), "scene mismatch")
            objects = {o.object_id_in_scene for o in scene.objects}
            require(all(i in objects for i in bindings.values()), "concrete existing instances required")
            require(held_object is None or held_object in objects, "unknown held object")
        operations = {op.operation_id: op for op in task.operations}
        require(len(operations) == len(task.operations), "duplicate operation ID")
        require(len({s.step_id for s in plan.steps}) == len(plan.steps), "duplicate step ID")
        require({s.operation_id for s in plan.steps} == set(operations), "operation coverage mismatch")
        order = {op.operation_id: i for i, op in enumerate(task.operations)}
        indices = [order[s.operation_id] for s in plan.steps]
        require(indices == sorted(indices), "operation order mismatch")
        held, completed = held_object, set()
        for op in task.operations:
            require(set(op.depends_on) <= completed, "unmet operation dependencies")
            actor = op.source or op.target
            require(actor in bindings, "missing actor")
            allowed = {r for r in (op.source, op.destination, op.target, op.reference) if r}
            require(allowed <= bindings.keys(), "unknown operation role")
            kind = op.task_type.value
            skills = {
                "locate": {"locate"},
                "grasp": {"locate", "move", "grasp"},
                "release": {"locate", "release"},
                "move": {"locate", "move", "grasp", "release"},
                "pick_and_place": {"locate", "move", "grasp", "release"},
                "press": {"locate", "move", "press"},
                "open": {"locate", "move", "grasp", "pull", "release"},
                "close": {"locate", "push"},
            }
            require(kind in skills, "unsupported task " + kind)
            contact = (op.reference or actor) if kind == "open" else actor
            initial_held = held
            if kind in {"move", "grasp", "pick_and_place", "open"} and held is not None and held != bindings[contact]:
                raise ValueError("holding_conflict: operation actor differs from held object")
            if kind == "pick_and_place":
                require(op.placement_target is not None and op.placement_target.reference == op.destination,
                        "placement reference differs from destination")
                require(bindings[actor] != bindings[op.destination], "self placement")
            located, reached, effects = set(), None, set()
            for step in (s for s in plan.steps if s.operation_id == op.operation_id):
                require(step.target_entity in allowed and step.target_entity in bindings, "step target role mismatch")
                require(step.reference_entity is None or step.reference_entity in allowed, "step reference role mismatch")
                skill = step.skill_name.value
                require(skill in skills[kind], "forbidden effect for operation")
                definition = REGISTRY.require(skill)
                require(step.region is None or step.region in definition.allowed_regions, "unsupported region")
                target = bindings[step.target_entity]
                if skill == "locate":
                    require(step.reference_entity is None, "locate has no reference")
                    located.add(target)
                elif skill == "move":
                    if step.region:
                        require(target in located, "move requires located target")
                        if step.region == "placement_region":
                            require(kind == "pick_and_place" and step.target_entity == op.destination
                                    and step.reference_entity == actor and held == bindings[actor], "placement move roles/holding mismatch")
                        else:
                            require(held is None, "approach with occupied gripper")
                            expected = "button_surface" if kind == "press" else "grasp_region"
                            require(kind in {"grasp", "move", "pick_and_place", "open", "press"}
                                    and step.region == expected and step.target_entity == contact
                                    and step.reference_entity is None and "released" not in effects, "approach actor mismatch")
                        reached = (target, step.region)
                    else:
                        require(kind == "move" and step.target_entity == actor and step.reference_entity is None
                                and held == target, "direction move requires matching held object")
                        require(op.distance_m is not None and op.motion_direction is not None, "missing displacement")
                        require("directional_move" not in effects, "duplicate displacement effect")
                        effects.add("directional_move")
                        reached = None
                elif skill == "grasp":
                    if held is not None:
                        raise ValueError("holding_conflict: gripper already occupied")
                    require(step.target_entity == contact and step.reference_entity is None
                            and reached == (target, "grasp_region") and "grasped" not in effects, "grasp precondition")
                    held = target
                    effects.add("grasped")
                    reached = None
                elif skill == "release":
                    require(held == target, "release requires matching held object")
                    require("released" not in effects, "duplicate release effect")
                    if kind == "pick_and_place":
                        require(step.target_entity == actor and step.reference_entity == op.destination
                                and step.region == "placement_region"
                                and reached == (bindings[op.destination], "placement_region"), "release placement mismatch")
                        effects.add("placement_release")
                    else:
                        require(step.target_entity == contact and step.reference_entity is None
                                and step.region is None, "release role mismatch")
                        require(kind != "move" or initial_held is None and "directional_move" in effects, "move release ordering")
                        require(kind != "open" or "pulled" in effects, "open release ordering")
                    held = None
                    reached = None
                    effects.add("released")
                elif skill == "press":
                    require(step.target_entity == actor and step.reference_entity is None and held is None
                            and reached == (target, "button_surface") and "pressed" not in effects, "press precondition")
                    effects.add("pressed")
                elif skill == "pull":
                    require(step.target_entity == actor and step.reference_entity == op.reference
                            and held == bindings[contact] and "pulled" not in effects, "pull precondition")
                    effects.add("pulled")
                elif skill == "push":
                    require(step.target_entity == actor and step.reference_entity == op.reference
                            and held is None and target in located and "pushed" not in effects, "push precondition")
                    effects.add("pushed")
            if kind == "locate":
                require(bindings[actor] in located and held == initial_held, "locate final state")
            elif kind == "grasp":
                require(held == bindings[actor], "grasp actor mismatch")
            elif kind == "release":
                require("released" in effects and held is None, "final release missing")
            elif kind == "move":
                require("directional_move" in effects, "direction move coverage")
                require(held == (None if initial_held is None else bindings[actor]), "move final holding")
            elif kind == "pick_and_place":
                require("placement_release" in effects and held is None, "final placement missing")
            elif kind == "press":
                require("pressed" in effects and held is None, "press effect missing")
            elif kind == "open":
                require("pulled" in effects and held is None, "open final state")
            elif kind == "close":
                require("pushed" in effects and held is None, "close effect missing")
            completed.add(op.operation_id)
        return plan
