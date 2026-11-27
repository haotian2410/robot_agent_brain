import pytest
from robot_agent_brain.contracts.control_skill_contract import ControlSkillContract
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.contracts.robot_setup import RobotRuntimeState
from robot_agent_brain.planning.atomic_operation_ir import AtomicOperationIR
from robot_agent_brain.planning.dual_arm_dag import build_commands_dag_from_ir
from robot_agent_brain.planning.dual_v4_holds import apply_hold_constraints


def fixture(*, initially_held=False, region=False):
    operations = ([] if initially_held else [dict(operation_id="op-hold", task_type="grasp", target="apple", arm="left")]) + [
        dict(operation_id="op-inspect", task_type="locate", target="banana", arm="right"),
        dict(operation_id="op-release", task_type="release", target="apple", arm="left")]
    hold = dict(kind="hold_during_operation", holder_arm="left", object_entity="apple", while_operation="op-inspect")
    if region:
        hold.update(kind="hold_until_operation", holder_operation="op-hold", region="placement_region", region_entity="banana")
    task = GroundedTask(instruction="左臂保持苹果直到右臂完成", scene_id=1, scene_version=2,
        entities=[dict(entity_id=name, semantic_name=name, category="fruit", scene_object_id=identifier)
                  for name, identifier in [("apple", 7), ("banana", 8)]],
        operations=operations, hold_constraints=[hold])
    skill_names = {"grasp": "custom_acquire", "locate": "custom_inspect", "release": "custom_release"}
    ir = [AtomicOperationIR(operation_id=op.operation_id, kind=op.task_type.value,
        source_object_id=7 if op.target == "apple" else 8, arm=op.arm) for op in task.operations]
    steps = {op.operation_id: [dict(skill_name=skill_names[op.kind], parameters={"object": op.source_object_id})] for op in ir}
    commands = build_commands_dag_from_ir(request_id="hold", scene_id=1, scene_version=2,
        scene_digest="d", robot_setup_revision=1, skill_contract_revision="test", operations=ir, skill_steps=steps)
    schema = {"type": "object", "properties": {"object": {"type": "integer"}}, "required": ["object"], "additionalProperties": False}
    contract = ControlSkillContract(revision="test", supported_protocols=["4.0"], expansion_level="atomic",
        supports_hold=True, skills={name: dict(expansion_level="atomic", parameters_schema=schema,
            object_parameters={"object": "source_object_id"}, holding_effect=effect)
            for name, effect in [("custom_acquire", {"action": "acquire", "object_parameter": "object"}),
                                 ("custom_inspect", {"action": "preserve"}), ("custom_release", {"action": "release"})]})
    runtime = RobotRuntimeState(arms={"left": {"state_known": True, "holding_object": 7 if initially_held else None},
                                     "right": {"state_known": True}})
    return commands, task, runtime, contract


def test_acquisition_and_release_are_anchored_without_wait_commands():
    commands, task, runtime, contract = fixture()
    result = apply_hold_constraints(commands, task, runtime, contract)
    hold = result.hold_constraints[0]
    assert hold.after_command_id == "L-op-hold-1"
    assert hold.until_command_id == "R-op-inspect-1"
    assert result.commands[1].depends_on == ["L-op-hold-1"]
    assert result.commands[2].depends_on == ["L-op-hold-1", "R-op-inspect-1"]
    assert [c.skill_name for c in result.commands] == [c.skill_name for c in commands.commands]
    contract.validate_commands(result)


def test_initial_actual_hold_does_not_invent_a_grasp():
    commands, task, runtime, contract = fixture(initially_held=True)
    result = apply_hold_constraints(commands, task, runtime, contract)
    assert result.hold_constraints[0].after_command_id is None
    assert len(result.commands) == 2
    assert result.commands[1].depends_on == ["R-op-inspect-1"]


@pytest.mark.parametrize("initially_held", [False, True])
def test_two_ordinary_acquisitions_cannot_disguise_handover(initially_held):
    commands, task, runtime, contract = fixture(initially_held=initially_held)
    receiver = next(c for c in commands.commands if c.operation_id == "op-inspect")
    receiver.skill_name = "custom_acquire"
    receiver.parameters = {"object": 7}
    before_commands = commands.model_dump(mode="json")
    before_runtime = runtime.model_dump(mode="json")
    with pytest.raises(ValueError, match="commands_v4_hold_conflicting_acquisition"):
        apply_hold_constraints(commands, task, runtime, contract)
    assert commands.model_dump(mode="json") == before_commands
    assert runtime.model_dump(mode="json") == before_runtime


def test_region_constraint_keeps_bound_region_and_holder_milestone():
    commands, task, runtime, contract = fixture(region=True)
    result = apply_hold_constraints(commands, task, runtime, contract)
    assert result.hold_constraints[0].region_object_id == 8
    assert result.hold_constraints[0].region == "placement_region"


def test_session_pipeline_exports_hold_events_without_predicted_runtime_writeback():
    from test_dual_v4_pipeline import setup
    from robot_agent_brain.contracts.turn import BrainTurn
    from robot_agent_brain.contracts.task_intent import TaskIntent
    session = setup()
    _, grounded, _, contract = fixture()
    session.pipeline.control_skill_contract = contract
    names = {"grasp": "custom_acquire", "locate": "custom_inspect", "release": "custom_release"}
    session.pipeline.dual_skill_recipe = lambda request: {"operations": [
        {"operation_id": op.operation_id, "steps": [{"skill_name": names[op.kind],
            "parameters": {"object": op.source_object_id}}]} for op in request.operations]}
    intent = TaskIntent(instruction=grounded.instruction,
        entities=[{"entity_id": e.entity_id, "semantic_name": e.semantic_name, "category": e.category}
                  for e in grounded.entities], operations=grounded.operations,
        hold_constraints=grounded.hold_constraints)
    before = session.arm_states.model_dump()
    result = session.process_turn("hold-chain", BrainTurn(status="accepted", turn_kind="robot_task",
        instruction=intent.instruction, task_intent=intent))
    assert result.commands.schema_version == "4.0"
    assert result.commands.hold_constraints[0].after_command_id == "L-op-hold-1"
    assert session.exported_commands["hold-chain"]["hold_constraints"][0]["object_id"] == 7
    assert session.arm_states.model_dump() == before


@pytest.mark.parametrize("fault,code", [
    ("unsupported", "control_dag_feature_unsupported"),
    ("effect", "holding_effect_missing"),
    ("wrong_object", "hold_not_established"),
    ("cycle", "dependency_cycle"),
])
def test_hold_failures_refuse_instead_of_dropping_constraints(fault, code):
    commands, task, runtime, contract = fixture()
    if fault == "unsupported":
        contract.supports_hold = False
    elif fault == "effect":
        contract.skills["custom_acquire"].holding_effect = None
    elif fault == "wrong_object":
        commands.commands[0].parameters["object"] = 8
    else:
        commands.commands[1].depends_on = [commands.commands[2].command_id]
    with pytest.raises(ValueError, match=code):
        apply_hold_constraints(commands, task, runtime, contract)
