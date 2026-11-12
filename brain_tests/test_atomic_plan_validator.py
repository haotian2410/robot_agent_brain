"""The assembly rules of skill.md, enforced in Python after the schema was dropped."""
import pytest
from robot_agent_brain.contracts.commands_atomic import AtomicCommand, AtomicCommandsFile
from robot_agent_brain.contracts.grounded_task import GroundedEntity
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.errors import BrainError
from robot_agent_brain.planning.atomic_plan_validator import (AtomicPlanValidator, PLACEMENT_EDGE_OFFSET_M,
                                                              SURFACE_CARRY_LIFT_M, SURFACE_CARRY_RETRACT_M)
from robot_agent_brain.planning.atomic_planner import expand_atomic_plan
from test_recipe_state import task

SOURCE, DESTINATION = 101, 102


def approach(source=True):
    return "approach", {"target": SOURCE if source else DESTINATION}


def pick(source=True):
    return "pick", {"target": SOURCE if source else DESTINATION}


def retreat(source=True):
    return "retreat", {"target": SOURCE if source else DESTINATION}


def put(**parameters):
    return "put", {"target": DESTINATION, **parameters}


LIFT = "lift_up", {}
HOME = "move_to", {"target": "home"}


def transfer(source, destination):
    return [("approach", {"target": source}), ("pick", {"target": source}), LIFT,
            ("retreat", {"target": source}), HOME, ("approach", {"target": destination}),
            ("put", {"target": destination}), ("retreat", {"target": destination})]


GOLDEN = transfer(SOURCE, DESTINATION)


def numbered(items):
    return [AtomicCommand(command_id=str(index), skill_name=skill, parameters=dict(parameters))
            for index, (skill, parameters) in enumerate(items, 1)]


def check(items, value=None, **kwargs):
    document = AtomicCommandsFile(request_id="r-1", scene_id=1, scene_version=0, commands=numbered(items))
    return AtomicPlanValidator().validate(document, value or placement_task(), **kwargs)


def placement_task(relation="inside", kind="container_interior", region=None):
    return task([Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="b",
                           placement_target={"kind": kind, "reference": "b", "relation": relation,
                                             **({"region": region} if region else {})})])


def without(*indexes):
    return [item for index, item in enumerate(GOLDEN) if index not in indexes]


def replace(index, item):
    return [item if position == index else original for position, original in enumerate(GOLDEN)]


def test_golden_assembly_graph_is_accepted():
    assert [item.skill_name.value for item in check(GOLDEN).commands] == [
        "approach", "pick", "lift_up", "retreat", "move_to", "approach", "put", "retreat"]


@pytest.mark.parametrize("item", [without(2), without(4), replace(2, HOME)])
def test_lift_and_transit_moves_are_optional(item):
    assert len(check(item).commands) == len(item)


@pytest.mark.parametrize("mutation,code", [
    (without(0), "atomic_plan_missing_approach"),
    (without(3), "atomic_plan_missing_retreat"),
    (without(7), "atomic_plan_missing_retreat"),
    (GOLDEN[:7] + [HOME, retreat(False)], "atomic_plan_retreat_not_adjacent"),
    (replace(2, approach(False)), "atomic_plan_pick_sequence_invalid"),
    (replace(5, pick()), "atomic_plan_gripper_occupied"),
    (GOLDEN[:5] + [approach(False), approach(False), put(), retreat(False)], "atomic_plan_duplicate_approach"),
    (GOLDEN[:1] + GOLDEN[5:], "atomic_plan_nothing_held"),
    ([LIFT, *GOLDEN], "atomic_plan_nothing_lifted"),
    (replace(6, ("put", {"target": 999})), "atomic_plan_unknown_target"),
])
def test_violations_report_their_own_code(mutation, code):
    with pytest.raises(BrainError) as error:
        check(mutation)
    assert error.value.issue.code == code


def test_object_that_no_operation_binds_is_rejected():
    value = placement_task()
    value.entities.append(GroundedEntity(entity_id="c", semantic_name="cup", scene_object_id=103, category="cup"))
    with pytest.raises(BrainError, match="atomic_plan_unbound_target"):
        check(GOLDEN + [approach(False), ("pick", {"target": 103})], value)


def test_put_must_landing_on_the_destination_of_its_operation():
    items = [approach(), pick(), LIFT, retreat(), HOME, approach(), ("put", {"target": SOURCE}), retreat()]
    with pytest.raises(BrainError, match="atomic_plan_put_target_mismatch"):
        check(items, placement_task())


def test_object_used_by_two_operations_is_allowed():
    value = task([Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="b",
                            placement_target={"kind": "container_interior", "reference": "b", "relation": "inside"}),
                  Operation(operation_id="op-2", task_type="pick_and_place", source="b", destination="a",
                            placement_target={"kind": "container_interior", "reference": "a", "relation": "inside"},
                            depends_on=["op-1"])])
    assert len(check(transfer(SOURCE, DESTINATION) + transfer(DESTINATION, SOURCE), value).commands) == 16


def two_independent_places():
    value = task([Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="c",
                            placement_target={"kind": "container_interior", "reference": "c", "relation": "inside"}),
                  Operation(operation_id="op-2", task_type="pick_and_place", source="b", destination="d",
                            placement_target={"kind": "container_interior", "reference": "d", "relation": "inside"},
                            depends_on=["op-1"])])
    value.entities += [GroundedEntity(entity_id="c", semantic_name="box", scene_object_id=103, category="container"),
                       GroundedEntity(entity_id="d", semantic_name="tray", scene_object_id=104, category="container")]
    return value


def test_operations_must_all_be_covered_and_in_order():
    value = two_independent_places()
    first, second = transfer(SOURCE, 103), transfer(DESTINATION, 104)
    assert len(check(first + second, value).commands) == 16
    with pytest.raises(BrainError, match="atomic_plan_operation_coverage_mismatch"):
        check(first, value)
    with pytest.raises(BrainError, match="atomic_plan_operation_order_mismatch"):
        check(second + first, value)


def test_collection_targets_reject_a_second_candidate():
    value = placement_task()
    value.entities[0] = GroundedEntity(entity_id="a", semantic_name="apple", scene_object_id=SOURCE,
                                       scene_object_ids=[SOURCE, DESTINATION], category="fruit")
    with pytest.raises(BrainError, match="atomic_plan_set_not_expanded"):
        check(GOLDEN, value)


def test_named_home_target_is_not_a_scene_object():
    assert check(GOLDEN).commands[4].parameters.target == "home"


@pytest.mark.parametrize("relation,kind,code", [
    ("inside", "container_interior", None),
    ("on", "support_surface", None),
    ("near", "relative_object", None),
    ("front_of", "relative_object", None),
    ("back", "relative_object", None),
    ("left", "relative_object", None),
    ("rightmost", "relative_object", None),
    ("above", "relative_object", None),
    ("below", "relative_object", None),
    ("down", "relative_object", None),
    ("highest", "relative_object", "atomic_plan_placement_relation_unsupported"),
])
def test_only_a_landing_the_control_put_can_reach_is_accepted(relation, kind, code):
    # The refusal is read from the semantic landing, not from what the model wrote:
    # a request the control cannot resolve must stop before the child is spawned.
    if code is None:
        assert len(check(GOLDEN, placement_task(relation, kind)).commands) == len(GOLDEN)
    else:
        with pytest.raises(BrainError, match=code):
            check(GOLDEN, placement_task(relation, kind))


def test_a_vertical_landing_onto_a_surface_stays_one_put():
    """「放到桌面上方」 hovers, so the surface no longer forces the four-step carry.

    The carry exists because a horizontal side lands beside the table box, out of
    every camera frame.  ``above`` is the one direction whose landing the control
    resolves from the box alone, so rewriting it into a carry would move the
    object somewhere the sentence did not say.
    """
    command = check(GOLDEN, placement_task("up", "support_surface"),
                    scene=scene_with_table("surface")).commands[6]
    assert command.skill_name.value == "put"
    assert (command.parameters.relation, command.parameters.distance_m) == ("above", PLACEMENT_EDGE_OFFSET_M)


def test_a_quadrant_landing_has_no_single_direction_reading():
    """「桌子左上角」 is two sides at once, so it stops instead of becoming「左边」."""
    with pytest.raises(BrainError, match="atomic_placement_region_unsupported"):
        check(GOLDEN, placement_task("left", "relative_object", region="left_front"))


@pytest.mark.parametrize("region,expected", [("left_half", "left"), ("right_half", "right"),
                                             ("front_half", "front"), ("back_half", "behind")])
def test_a_half_landing_is_the_side_it_names(region, expected):
    """「放到桌子左边」 says one side, and ``put`` offsets exactly that side.

    The refusal used to cover every region, so the ordinary four-way wording an
    user actually says was stopped while the corner wording that cannot be done
    was the only honest refusal left.
    """
    parameters = check(replace(6, put()), placement_task("on", "support_surface",
                                                        region=region)).commands[6].parameters
    assert (parameters.relation, parameters.distance_m) == (expected, PLACEMENT_EDGE_OFFSET_M)


def test_a_side_and_a_region_that_name_different_sides_is_refused():
    with pytest.raises(BrainError, match="atomic_plan_placement_region_conflict"):
        check(GOLDEN, placement_task("right", "relative_object", region="left_half"))


@pytest.mark.parametrize("relation,expected", [("front_of", "front"), ("leftmost", "left"),
                                               ("back", "behind"), ("right_of", "right")])
def test_a_requested_side_reaches_the_wire_even_if_the_answer_omits_it(relation, expected):
    """The task owns the landing side; the planning round only owns the graph."""
    def landing(items):
        parameters = check(items, placement_task(relation, "relative_object")).commands[6].parameters
        return parameters.relation, parameters.distance_m

    assert landing(replace(6, put())) == (expected, PLACEMENT_EDGE_OFFSET_M)
    # A guessed side or distance is the model's invention, not something the user said.
    assert landing(replace(6, put(relation="left", distance_m=0.9))) == (expected, PLACEMENT_EDGE_OFFSET_M)


def test_an_invented_side_on_a_plain_landing_is_removed():
    assert check(replace(6, put(relation="front", distance_m=0.2))).commands[6].parameters.distance_m is None


def drawer():
    return task([Operation(operation_id="op-1", task_type="open", target="a", reference="b")])


STROKE = {"distance": 0.16, "frame": "grasp"}


def test_a_drawer_stroke_belongs_between_the_grip_and_the_retreat():
    items = [approach(), pick(), ("pull", STROKE), retreat()]
    assert len(check(items, drawer()).commands) == 4
    both = items + [approach(), pick(), ("push", STROKE), retreat()]
    assert len(check(both, drawer()).commands) == 8


@pytest.mark.parametrize("items", [
    [approach(), ("pull", STROKE), retreat()],
    [("pull", STROKE), approach(), pick(), retreat()],
])
def test_a_stroke_needs_a_grip_before_it(items):
    with pytest.raises(BrainError, match="atomic_plan_nothing_pulled"):
        check(items, drawer())


def test_the_recipe_graph_grips_the_handle_and_drives_one_stroke():
    """「打开抽屉」 used to stop at the capability gate even though control has pull/push."""

    def shape(value):
        document = AtomicCommandsFile(request_id="r-1", scene_id=1, scene_version=0,
                                      commands=expand_atomic_plan(value))
        return [(item.skill_name.value, item.parameters.model_dump(mode="json", exclude_none=True))
                for item in AtomicPlanValidator().validate(document, value).commands]

    # The handle is the operation's reference, which is what the grip closes on.
    assert shape(drawer()) == [("approach", {"target": 102}), ("pick", {"target": 102}),
                               ("pull", STROKE), ("retreat", {"target": 102})]
    assert shape(task([Operation(operation_id="op-1", task_type="close", target="a", reference="b")]))[2] == \
        ("push", STROKE)


def test_scene_binding_is_checked_only_when_a_scene_is_given():
    scene = SceneConfig.model_validate({"scene_schema_version": 1, "scene_version": 7, "scene_id": 1,
                                        "scene_name": "s", "objects": []})
    with pytest.raises(BrainError, match="atomic_plan_scene_mismatch"):
        check(GOLDEN, scene=scene)


def test_a_side_onto_the_work_table_becomes_a_carry_and_a_release():
    """「放到桌子左边」 asks for a landing *on* the table, and the dialect can say it.

    Control reads a ``put`` side as the destination's own box released on that one
    side, and a work table's box is the whole working area, so the offset lands ten
    centimetres past the tabletop edge at the height of the box centre -- a point no
    RGB-D frame observes, which the live stack reported only after a four-minute run.
    The carry never addresses such a point: it offsets the hand from where it stands
    and opens the gripper there, so the landing stays on the tabletop.
    """
    commands = check(GOLDEN, placement_task("left", "relative_object", region="left_half"),
                     scene=scene_with_table("surface")).commands
    assert len(commands) == len(GOLDEN) + 3
    shape = [(command.skill_name.value,
              command.parameters.model_dump(mode="json", exclude_none=True))
             for command in commands[6:10]]
    assert shape == [
        ("move_to", {"target": "end_effector", "relation": "above", "distance_m": SURFACE_CARRY_LIFT_M,
                     "planning_method": "linear", "keep_end_effector_orientation": True}),
        ("move_to", {"target": "end_effector", "relation": "left", "distance_m": PLACEMENT_EDGE_OFFSET_M,
                     "planning_method": "linear", "keep_end_effector_orientation": True}),
        ("release", {"target": SOURCE}),
        ("move_to", {"target": "end_effector", "relation": "above", "distance_m": SURFACE_CARRY_RETRACT_M,
                     "planning_method": "linear", "keep_end_effector_orientation": True})]
    # The put is gone, so nothing is asked of the destination box, and the ids stay
    # the sequential labels the report quotes back.
    assert [command.command_id for command in commands] == [str(number) for number in range(1, len(commands) + 1)]
    assert all(command.skill_name.value != "put" for command in commands)


def test_a_release_needs_the_grip_on_that_very_object():
    with pytest.raises(BrainError, match="atomic_plan_release_without_grasp"):
        check([approach(), pick(), LIFT, ("release", {"target": DESTINATION}), retreat()])


def test_a_carry_and_release_closes_the_interaction_it_started():
    carry = ("move_to", {"target": "end_effector", "relation": "left", "distance_m": 0.1,
                         "planning_method": "linear", "keep_end_effector_orientation": True})
    assert len(check([approach(), pick(), LIFT, carry, ("release", {"target": SOURCE}),
                      retreat()]).commands) == 6


def scene_with_table(category):
    """The two-task objects, the destination carrying the category under test."""
    def entry(identifier, name, kind):
        return {"object_id_in_scene": identifier, "object_name_in_scene": name,
                "components": [{"component_type": "Transform",
                                "properties": {"position": [0., 0., 0.], "quaternion_xyzw": [0., 0., 0., 1.],
                                               "scale": [1., 1., 1.], "parent": None}},
                               {"component_type": "Semantic",
                                "properties": {"semantic_name": name, "category": kind, "support": None}}]}
    return SceneConfig.model_validate({"scene_schema_version": 1, "scene_version": 0, "scene_id": 1,
                                       "scene_name": "s",
                                       "objects": [entry(SOURCE, "Apple", "graspable"),
                                                   entry(DESTINATION, "WorkTable", category)]})


def test_a_side_onto_a_container_is_still_pinned_to_that_side():
    """The refusal is about the surface's own box, so a container keeps its landing."""
    command = check(GOLDEN, placement_task("left", "relative_object", region="left_half"),
                    scene=scene_with_table("placement")).commands[6]
    assert (command.parameters.relation, command.parameters.distance_m) == ("left", PLACEMENT_EDGE_OFFSET_M)
