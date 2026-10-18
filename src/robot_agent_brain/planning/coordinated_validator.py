"""Conservative symbolic stage checking, not execution or collision evidence.

The returned state assumes successful execution of every action. Never persist
it as measured runtime state; Control feedback is required for that purpose.
"""
from dataclasses import dataclass, field
from copy import deepcopy

from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
from robot_agent_brain.contracts.robot_setup import RobotRuntimeState


@dataclass
class CoordinatedState:
    holding: dict[str, int | None]
    located: set[int] = field(default_factory=set)
    reached: dict[str, tuple[int, str] | None] = field(default_factory=dict)


class CoordinatedValidator:
    def validate(self, plan: CommandsFileV3, runtime: RobotRuntimeState) -> CoordinatedState:
        from .coordinated_scheduler import validate_stage_order
        validate_stage_order(plan)
        if set(runtime.arms) != {"left", "right"}:
            raise ValueError("robot_runtime_arm_mapping_invalid")
        if any(not arm.state_known for arm in runtime.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        held = [a.holding_object for a in runtime.arms.values() if a.holding_object is not None]
        if len(held) != len(set(held)):
            raise ValueError("dual_shared_ownership_unsupported")
        state = CoordinatedState({side: a.holding_object for side, a in runtime.arms.items()})
        for index, stage in enumerate(plan.steps):
            before = deepcopy(state)
            for condition in [*stage.preconditions, *stage.invariants]:
                if not self._holds(condition, before):
                    raise ValueError("dual_condition_unproven: " + condition.predicate)
            actions = [(side, getattr(stage.arms, side)) for side in ("left", "right")
                       if getattr(stage.arms, side) is not None]
            resources = []
            for side, action in actions:
                resources.append(self._check_action(side, action, before))
            from .dual_condition_builder import require_condition_coverage
            require_condition_coverage(stage, plan, index)
            if len(resources) == 2:
                reads_a, writes_a = resources[0]
                reads_b, writes_b = resources[1]
                if writes_a & (reads_b | writes_b) or writes_b & (reads_a | writes_a):
                    raise ValueError("dual_stage_resource_conflict")
            # Invariants cannot depend on facts changed during the stage, even
            # if they would become true again at the final endpoint.
            for side, action in actions:
                candidate = deepcopy(before)
                self._apply(side, action, candidate)
                for condition in stage.invariants:
                    if (condition.predicate == "holding" and condition.arm == side
                            and action.skill_name.value in {"move", "release"}):
                        raise ValueError("dual_invariant_conflict: explicit stable hold")
                    if (condition.predicate == "at_region" and condition.arm == side
                            and action.skill_name.value == "move"):
                        raise ValueError("dual_invariant_conflict")
                    if not self._holds(condition, candidate):
                        raise ValueError("dual_invariant_conflict")
            for side, action in actions:
                self._apply(side, action, state)
        return state

    @staticmethod
    def _holds(c, state):
        if c.predicate == "holding":
            return state.holding[c.arm] == c.object_id
        if c.predicate == "gripper_empty":
            return state.holding[c.arm] is None
        if c.predicate == "located":
            return c.object_id in state.located
        return state.reached.get(c.arm) == (c.object_id, c.region)

    @staticmethod
    def _check_action(side, action, state):
        p = action.parameters
        target = p.target
        kind = action.skill_name.value
        held = state.holding[side]
        other_held = state.holding["right" if side == "left" else "left"]
        reads, writes = {target}, set()
        if kind == "locate":
            return reads, writes
        if kind == "move":
            # v2 skill convention: move.target is the approached object;
            # move.reference may be the carried object (not the destination).
            reference = target
            if p.reference is not None and p.reference != held:
                raise ValueError("dual_move_carried_reference_mismatch")
            reads.add(reference)
            if p.region is None:
                if held != target:
                    raise ValueError("dual_move_requires_holding")
            elif reference not in state.located:
                raise ValueError("dual_move_requires_located")
            if held is not None:
                writes.add(held)
            if other_held in reads:
                raise ValueError("dual_reference_held_by_other_arm_unsupported")
        elif kind == "grasp":
            if held is not None or target == other_held:
                raise ValueError("dual_grasp_ownership_conflict")
            if state.reached.get(side) != (target, "grasp_region"):
                raise ValueError("dual_grasp_requires_reached")
            writes.add(target)
        elif kind == "release":
            if held != target:
                raise ValueError("dual_release_requires_holding")
            reference = p.reference if p.reference is not None else target
            reads.add(reference)
            if p.region is not None and (p.region != "placement_region" or state.reached.get(side) != (reference, "placement_region")):
                raise ValueError("dual_release_requires_reached")
            if p.region is None and p.reference is not None:
                raise ValueError("dual_release_reference_requires_region")
            writes.add(target)
        return reads, writes

    @staticmethod
    def _apply(side, action, state):
        p = action.parameters
        kind = action.skill_name.value
        moved = None
        if kind == "locate":
            state.located.add(p.target)
            return
        if kind == "move":
            moved = state.holding[side]
            state.reached[side] = None
        elif kind == "grasp":
            state.holding[side] = p.target
            moved = p.target
        elif kind == "release":
            state.holding[side] = None
            state.reached[side] = None
            moved = p.target
        if moved is not None:
            state.located.discard(moved)
            for arm, region in list(state.reached.items()):
                if region is not None and region[0] == moved:
                    state.reached[arm] = None
        if kind == "move" and p.region is not None:
            state.reached[side] = (p.target, p.region)
