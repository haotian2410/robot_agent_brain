"""Deterministic guard for the control atomic-skill document.

The planning round no longer answers through a strict json_schema, so this
validator is the only place where the control assembly graph is enforced.  It
never repairs the graph: an illegal sequence is a model-output failure, and
silently inserting a missing ``retreat`` would turn the specification into a
suggestion.  What it does rewrite is the *landing*: where the task, and not the
answer, is the authority -- see ``_pin_placement`` and ``_surface_carry``.
"""
from __future__ import annotations

from ..contracts.commands_atomic import (AtomicCommand, AtomicCommandsFile, AtomicSkillName,
                                         MoveToParameters, ReleaseParameters)
from ..contracts.grounded_task import GroundedTask
from ..contracts.scene import SceneConfig
from ..errors import BrainError
from ..scene.component_access import SceneIndex

# Between a pick and its retreat the graph allows only a vertical lift, a transit
# move and the drawer strokes; a pull/push belongs there because the control ends
# it by opening the gripper, so nothing after it may assume the object is held.
PICK_TRAILING = frozenset({AtomicSkillName.LIFT_UP, AtomicSkillName.MOVE_TO,
                           AtomicSkillName.PULL, AtomicSkillName.PUSH, AtomicSkillName.RELEASE})
# ``demo/interaction/relative_placement.py`` resolves these four horizontal sides
# outside the destination's own box, and the semantic vocabulary spells each side
# several ways.  Anything that maps onto one of them is expressible as a ``put``
# offset, so it no longer needs to be refused.
PUT_LATERAL_RELATIONS = {"left": "left", "left_of": "left", "leftmost": "left",
                         "right": "right", "right_of": "right", "rightmost": "right",
                         "front": "front", "front_of": "front", "frontmost": "front",
                         "back": "behind", "backmost": "behind", "behind": "behind"}
# The same module resolves ``above``/``below`` along world Z since control commit
# ``b24cc3f``: it offsets the destination box and releases in the air, without
# VLM, depth or the height ladder.  A superlative is not one of these -- 「最高」
# picks among objects, it does not describe a landing.
PUT_VERTICAL_RELATIONS = {"up": "above", "above": "above", "down": "below", "below": "below"}
PUT_LATERAL_DIRECTIONS = frozenset(PUT_LATERAL_RELATIONS.values())
# A landing without a side is the destination's own spot, which is what the
# control does when it is given no relation at all.
PLACEMENT_RELATION_FREE = frozenset({"at", "inside", "on", "near"})
# A tabletop half names exactly one side, so 「放到桌子左边」 and 「向左放」 ask the
# control for the same landing: that side of the destination's own box.  Corners
# are deliberately absent -- they need two sides at once, which one ``put``
# offset cannot express, and this round no longer produces them at all.
REGION_LATERAL_RELATIONS = {"left_half": "left", "right_half": "right",
                            "front_half": "front", "back_half": "behind"}
# Superlatives are the only vertical words left with no reading as a landing:
# 「最高/最低」 rank candidate objects, and the control has no command that means
# "release at the top of the world".
UNSUPPORTED_PLACEMENT_RELATIONS = frozenset({"highest", "lowest"})
# The task vocabulary says which side, never how far: the semantic contract has no
# distance for an arm placement, so the Brain fixes one clearance and the planning
# round is not asked to invent it.
PLACEMENT_EDGE_OFFSET_M = 0.1
# Control projects the *destination's own box* and releases one side of it, so the
# landing of a ``put`` side request is always outside that box.  For a container that
# is the rim-to-rim opening and the placement works; for a work table the box is the
# whole working area, so 「放到桌子左边」 asks for a point beside the table, in the air
# at the height of the box centre -- a landing no RGB-D frame observes.  A side onto a
# surface is therefore not a ``put`` at all: the dialect says it as a carry, because
# ``move_to(target="end_effector", relation, distance_m)`` translates the hand while it
# keeps the grasp and ``release`` opens the gripper where the hand stands.  Neither
# command addresses a point outside the tabletop, so no scene geometry is consulted and
# the words the user said survive -- see ``_surface_carry``.
SURFACE_CATEGORIES = frozenset({"surface", "support_surface", "table"})
# The hand has to clear the rim of the container the object came out of before it
# travels: carrying sideways at the ``lift_up`` default of 2 cm dragged the gripper
# base into the basket (``robotiq_2f85_base`` x ``Basket``, 50.6 mm) on the live stack.
SURFACE_CARRY_LIFT_M = 0.08
# How far the hand backs off once the object is let go, so the retraction path does
# not have to be planned through the object it just dropped.
SURFACE_CARRY_RETRACT_M = 0.10


class AtomicPlanValidator:
    def validate(self, commands: AtomicCommandsFile, task: GroundedTask, scene: SceneConfig | None = None,
                 *, held_object=None) -> AtomicCommandsFile:
        bindings = {entity.entity_id: entity.scene_object_ids for entity in task.entities}
        if any(len(object_ids) != 1 for object_ids in bindings.values()):
            self.fail("atomic_plan_set_not_expanded", "规划前必须把类别实体展开为单个实例")
        known = {object_ids[0] for object_ids in bindings.values()}
        scene_index = None
        if scene is not None:
            if (task.scene_id, task.scene_version) != (scene.scene_id, scene.scene_version):
                self.fail("atomic_plan_scene_mismatch", "任务与场景版本不一致")
            known |= {item.object_id_in_scene for item in scene.objects}
            scene_index = SceneIndex(scene)
        operations = list(task.operations)
        # One object may appear in several operations ("先把苹果放进篮子，再把它拿出来"),
        # so each object carries the operations that bind it in order and the cursor
        # advances when an interaction with that object is closed by a retreat.
        operations_for_object: dict[int, list[int]] = {}
        placement_for_operation: dict[int, object] = {}
        destination_for_operation: dict[int, int] = {}
        for position, operation in enumerate(operations):
            for role in ("source", "destination", "target", "reference"):
                entity_id = getattr(operation, role)
                if entity_id in bindings:
                    positions = operations_for_object.setdefault(bindings[entity_id][0], [])
                    if not positions or positions[-1] != position:
                        positions.append(position)
            landing = operation.destination or operation.reference
            if landing in bindings:
                destination_for_operation[position] = bindings[landing][0]
                if operation.placement_target is not None:
                    placement_for_operation[position] = operation.placement_target

        cursor = {target: 0 for target in operations_for_object}
        held = held_object
        open_interaction: dict[int, AtomicSkillName] = {}
        interaction_index: dict[int, int] = {}
        covered: list[int] = []
        pinned: dict[int, AtomicCommand] = {}
        expanded: dict[int, list[AtomicCommand]] = {}
        for index, command in enumerate(commands.commands):
            skill = command.skill_name
            target = getattr(command.parameters, "target", None)
            if target is None:
                if skill is AtomicSkillName.LIFT_UP and held is None:
                    self.fail("atomic_plan_nothing_lifted", "lift_up 只在抓住物体之后、撤离之前执行")
                if skill in {AtomicSkillName.PULL, AtomicSkillName.PUSH}:
                    if held is None:
                        self.fail("atomic_plan_nothing_pulled",
                                  f"第 {index + 1} 条 {skill.value} 之前没有夹持任何物体")
                    # A finished stroke releases the handle on the control's side,
                    # so the next pull has to grip again.
                    held = None
                continue
            if isinstance(target, str):
                continue
            if target not in known:
                self.fail("atomic_plan_unknown_target", f"第 {index + 1} 条命令的 target {target} 不在本场景对象中")
            if skill is AtomicSkillName.MOVE_TO:
                continue
            positions = operations_for_object.get(target)
            if not positions:
                self.fail("atomic_plan_unbound_target", f"target {target} 不属于本次任务的任何 operation")
            position = positions[cursor[target]]
            if not covered or covered[-1] != position:
                covered.append(position)

            if skill is AtomicSkillName.APPROACH:
                if target in open_interaction:
                    self.fail("atomic_plan_duplicate_approach", f"target {target} 的 approach 尚未被交互消费")
                open_interaction[target] = skill
                interaction_index[target] = index
            elif skill is AtomicSkillName.PICK:
                if held is not None:
                    self.fail("atomic_plan_gripper_occupied", f"第 {index + 1} 条 pick 之前夹爪仍持有 {held}")
                self._require_approach(open_interaction, target, "pick")
                open_interaction[target] = skill
                interaction_index[target] = index
                held = target
            elif skill is AtomicSkillName.PUT:
                if held is None:
                    self.fail("atomic_plan_nothing_held", f"第 {index + 1} 条 put 之前没有夹持任何物体")
                self._require_approach(open_interaction, target, "put")
                if destination_for_operation.get(position, target) != target:
                    self.fail("atomic_plan_put_target_mismatch",
                              f"第 {index + 1} 条 put 的落点应为 {destination_for_operation[position]}，写成 {target}")
                destination = scene_index.semantic(target) if scene_index is not None else None
                category = (destination.category if destination is not None else "") or ""
                placement = placement_for_operation.get(position)
                self._check_placement_relation(placement)
                side = self._placement_direction(placement)
                if (side in PUT_LATERAL_DIRECTIONS
                        and category.casefold() in SURFACE_CATEGORIES):
                    # A horizontal side onto a surface has no ``put`` in this dialect;
                    # the carry below is the only shape that lands it where the
                    # sentence said.  ``above``/``below`` are not carried: the control
                    # offsets the surface's own box along Z and releases in the air.
                    expanded[index] = self._surface_carry(command.command_id, side, held)
                else:
                    replacement = self._pin_placement(command, placement)
                    if replacement is not None:
                        pinned[index] = replacement
                open_interaction[target] = skill
                interaction_index[target] = index
                held = None
            elif skill is AtomicSkillName.RELEASE:
                if held != target:
                    self.fail("atomic_plan_release_without_grasp",
                              f"第 {index + 1} 条 release 之前夹爪握住的是 {held}，不是 {target}")
                held = None
            elif skill is AtomicSkillName.RETREAT:
                action = open_interaction.pop(target, None)
                if action is None:
                    self.fail("atomic_plan_retreat_without_interaction", f"retreat {target} 没有可沿用的交互朝向")
                if action is AtomicSkillName.PUT:
                    if index != interaction_index.pop(target) + 1:
                        self.fail("atomic_plan_retreat_not_adjacent", "put 之后必须紧跟同一 target 的 retreat")
                else:
                    between = commands.commands[interaction_index.pop(target) + 1:index]
                    if any(item.skill_name not in PICK_TRAILING for item in between):
                        self.fail("atomic_plan_pick_sequence_invalid", "pick 与 retreat 之间只允许 lift_up 或 move_to")
                if cursor[target] + 1 < len(operations_for_object[target]):
                    cursor[target] += 1

        if open_interaction:
            self.fail("atomic_plan_missing_retreat", "以下 target 的交互没有对应 retreat: "
                                                    + ",".join(str(key) for key in sorted(open_interaction)))
        if not covered:
            self.fail("atomic_plan_operation_coverage_mismatch", "没有任何命令属于本次任务的 operation")
        if any(later < earlier for earlier, later in zip(covered, covered[1:])):
            self.fail("atomic_plan_operation_order_mismatch", "命令顺序与 operation 顺序不一致")
        missing = [op.operation_id for position, op in enumerate(operations) if position not in set(covered)]
        if missing:
            self.fail("atomic_plan_operation_coverage_mismatch",
                      "以下 operation 没有任何对应命令: " + ",".join(sorted(missing)))
        if scene is not None and held is not None and held not in known:
            self.fail("atomic_plan_unknown_held_object", f"结束时持有的 {held} 不在场景中")
        if pinned or expanded:
            # The carry replaces one command with four, so the ids are re-issued in
            # order; they are labels for the report, not references the model keeps.
            rebuilt = [command for index, item in enumerate(commands.commands)
                       for command in (expanded.get(index) or [pinned.get(index, item)])]
            commands = commands.model_copy(update={
                "commands": [command.model_copy(update={"command_id": str(position)})
                             for position, command in enumerate(rebuilt, start=1)]})
        return commands

    @staticmethod
    def _surface_carry(command_id, side, held):
        """Hold, translate the hand, open the gripper, back away.

        ``move_to`` with an ``end_effector`` target offsets from the measured pose of
        that very command, so the four steps chain into one horizontal landing at the
        height the object was carried at; only then does ``release`` let go, which the
        control does with no motion and no support check of its own.
        """
        def move(step, relation, distance):
            return AtomicCommand(
                command_id=f"{command_id}-{step}", skill_name=AtomicSkillName.MOVE_TO,
                parameters=MoveToParameters(target="end_effector", relation=relation, distance_m=distance,
                                            planning_method="linear", keep_end_effector_orientation=True))
        return [move("clear", "above", SURFACE_CARRY_LIFT_M), move(side, side, PLACEMENT_EDGE_OFFSET_M),
                AtomicCommand(command_id=f"{command_id}-release", skill_name=AtomicSkillName.RELEASE,
                              parameters=ReleaseParameters(target=held)),
                move("away", "above", SURFACE_CARRY_RETRACT_M)]

    def _require_approach(self, open_interaction, target, skill):
        if open_interaction.get(target) is not AtomicSkillName.APPROACH:
            self.fail("atomic_plan_missing_approach", f"{skill} {target} 之前缺少同一 target 的 approach")

    @staticmethod
    def _placement_direction(placement):
        """The one side this placement asks for, or None when it asks for none.

        Both the refusal and the ``put`` offset are read from here, so a half
        region and a lateral relation cannot be checked one way and pinned
        another.
        """
        if placement is None:
            return None
        relation = str(placement.relation) if placement.relation is not None else None
        side = (PUT_LATERAL_RELATIONS.get(relation) or PUT_VERTICAL_RELATIONS.get(relation)
                if relation is not None else None)
        if placement.region is None:
            return side
        region_side = REGION_LATERAL_RELATIONS.get(placement.region)
        if region_side is None:
            # A quadrant is an editor concept: it needs two sides at once, and
            # dropping the second one silently would land the object somewhere
            # the user never named.  The code carries no ``atomic_plan_`` prefix
            # on purpose: that prefix is what tells the planning round to spend a
            # repair turn, and no re-drafted command list can make a landing the
            # task itself never asked for.
            raise BrainError("atomic_placement_region_unsupported", "skill_planning",
                             f"控制端 put 只能沿单一方向偏移，无法表达桌面区域 {placement.region} 的落点")
        if side is not None and side != region_side:
            raise BrainError("atomic_plan_placement_region_conflict", "skill_planning",
                             f"落点同时要求 {relation} 和 {placement.region}，控制端只能沿一个方向偏移")
        return region_side if side is None else side

    @classmethod
    def _check_placement_relation(cls, placement):
        """Stop at a landing the ``put`` has no direction for at all.

        A horizontal side onto a support surface is not in here: this dialect
        reaches that landing as a carry, and the caller expands it -- see
        ``_surface_carry``.
        """
        side = cls._placement_direction(placement)
        if side is not None:
            return
        if placement is None or placement.relation is None:
            return
        declared = str(placement.relation)
        if declared in PLACEMENT_RELATION_FREE:
            return
        if declared in UNSUPPORTED_PLACEMENT_RELATIONS:
            raise BrainError("atomic_plan_placement_relation_unsupported", "skill_planning",
                             f"{declared} 是对多个对象的排序，不是目的地附近的落点")
        raise BrainError("atomic_plan_placement_relation_unsupported", "skill_planning",
                         f"控制端 put 无法表达 {declared} 方向的落点")

    @classmethod
    def _pin_placement(cls, command, placement):
        """Make the ``put`` offset say exactly what the task asked for.

        Control reads a lateral relation as an instruction -- it projects the
        destination box and releases that one side out -- so an offset the task
        never requested has to go, and one it did request has to survive even when
        the planning round leaves it out.  The distance is never the model's call:
        the task vocabulary has no distance for a placement.
        """
        current = command.parameters
        declared = cls._placement_direction(placement)
        expected = (None, None) if declared is None else (declared, PLACEMENT_EDGE_OFFSET_M)
        if (current.relation, current.distance_m) == expected:
            return None
        return command.model_copy(update={"parameters":
                                          current.model_copy(update={"relation": expected[0],
                                                                      "distance_m": expected[1]})})

    @staticmethod
    def fail(code, detail):
        raise BrainError(code, "skill_planning", detail)
