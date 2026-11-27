import pytest
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.web.protocol import digest
from test_dual_session_pipeline import configured, task
from test_control_skill_contract import contract
from test_layout_qwen_planning import provider_for


def setup(mode="recipe"):
    session, registry = configured(mode=mode)
    data = registry.model_dump()
    data["profiles"]["fixture_only"]["commands_version"] = "4.1"
    registry = RobotProfileRegistry.model_validate(data)
    session.robot_profiles = registry
    session.initialize_scene(session.scene)
    session.bind_imported_profile(registry.profiles["fixture_only"])
    capabilities = contract()
    capabilities["skills"]["pick"]["object_parameters"] = {"source": "source_object_id"}
    session.pipeline.control_skill_contract = capabilities
    session.pipeline.dual_skill_recipe = lambda request: {"operations": [
        {"operation_id": op.operation_id, "steps": [{"skill_name": "pick",
            "parameters": {"source": op.source_object_id}}]} for op in request.operations]}
    return session


def test_explicit_v4_profile_uses_negotiated_dag_without_legacy_planner():
    session = setup()
    result = session.process_turn("v4", task("right"))
    assert result.commands.schema_version == "4.1"
    assert result.commands.scene_digest == digest(session.scene)
    assert result.commands.commands[0].arm == "right"
    assert result.commands.commands[0].parameters == {"source": 7}
    assert result.planner_trace["arm_assignment"][0]["source"] == "explicit_arm"
    assert session.exported_commands["v4"]["schema_version"] == "4.1"
    # A successful plan does not change the real gripper or claim dispatch.
    assert session.arm_states.arms["right"].holding_object is None


@pytest.mark.parametrize("second_arm,explicit", [("right", False), ("right", True), ("left", False)])
def test_full_v4_pipeline_does_not_invent_cross_arm_barriers(second_arm, explicit):
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    session = setup()
    turn = TaskParseOutput.model_validate({"entities": [
        {"id": "apple", "name": "apple", "category": "fruit"},
        {"id": "banana", "name": "banana", "category": "fruit"}], "operations": [
        {"type": "grasp", "target": "apple", "arm": "left"},
        {"type": "grasp", "target": "banana", "arm": second_arm,
         "depends_on": ["op-1"] if explicit else []}]}).to_brain_turn("两个抓取任务")
    result = session.process_turn("barriers", turn)
    first, second = result.commands.commands
    assert not first.depends_on
    assert second.depends_on == ([first.command_id] if explicit or second_arm == "left" else [])


def test_v4_expansion_keeps_same_physical_actor_order_across_aliases():
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    from robot_agent_brain.planning.task_expander import TaskExpander
    grounded = GroundedTask(instruction="同一对象", scene_id=1, scene_version=1,
        entities=[{"entity_id": name, "semantic_name": "apple", "category": "fruit", "scene_object_id": 7}
                  for name in ("a", "alias")], operations=[
            {"operation_id": "op-one", "task_type": "grasp", "target": "a", "arm": "left"},
            {"operation_id": "op-two", "task_type": "grasp", "target": "alias", "arm": "right"}])
    expanded = TaskExpander().expand(grounded, serial_barriers=False)
    assert expanded.operations[1].depends_on == []


@pytest.mark.parametrize("reverse", [False, True])
def test_v4_expansion_orders_reference_and_actor_conflicts(reverse):
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    from robot_agent_brain.planning.task_expander import TaskExpander
    operations = [
        {"task_type": "grasp", "target": "apple", "arm": "left"},
        {"task_type": "pick_and_place", "source": "banana", "destination": "apple",
         "arm": "right", "placement_target": {"kind": "support_surface", "reference": "apple", "relation": "on"}}]
    if reverse:
        operations.reverse()
    for i, op in enumerate(operations, 1):
        op["operation_id"] = f"op-{i}"
    grounded = GroundedTask(instruction="对象依赖", scene_id=1, scene_version=1,
        entities=[{"entity_id": name, "semantic_name": name, "category": "fruit", "scene_object_id": oid}
                  for name, oid in (("apple", 7), ("banana", 8))], operations=operations)
    result = TaskExpander().expand(grounded, serial_barriers=False)
    assert result.operations[1].depends_on == []


def test_v4_shared_destination_does_not_become_whole_operation_barrier():
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    from robot_agent_brain.planning.task_expander import TaskExpander
    task = GroundedTask(instruction="分别放入篮子", scene_id=1, scene_version=1,
        entities=[{"entity_id": name, "semantic_name": name, "category": "object", "scene_object_id": oid}
                  for name, oid in (("apple", 7), ("banana", 8), ("basket", 9))],
        operations=[{"operation_id": f"op-{i}", "task_type": "pick_and_place", "source": source,
                     "destination": "basket", "arm": arm,
                     "placement_target": {"kind": "container_interior", "reference": "basket", "relation": "inside"}}
                    for i, source, arm in ((1, "apple", "left"), (2, "banana", "right"))])
    result = TaskExpander().expand(task, serial_barriers=False)
    assert all(not op.depends_on for op in result.operations)
    # Resource-window serialization is the DAG planner's responsibility.


def test_missing_controller_contract_cannot_fall_back_to_v3():
    session = setup()
    session.pipeline.control_skill_contract = None
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        session.process_turn("missing", task())
    assert not session.exported_commands


@pytest.mark.parametrize("advertisement", ["missing", "v3_only", "invalid"])
def test_contract_preflight_precedes_unlocked_arm_assignment(monkeypatch, advertisement):
    session = setup("qwen")
    if advertisement == "missing":
        session.pipeline.control_skill_contract = None
    elif advertisement == "v3_only":
        session.pipeline.control_skill_contract["supported_protocols"] = ["3.0"]
    else:
        session.pipeline.control_skill_contract["supports_sync"] = "true"
    calls = []

    def forbidden_assignment(*args, **kwargs):
        calls.append("assignment")
        raise AssertionError("unsupported protocol must not request camera or assignment")

    monkeypatch.setattr("robot_agent_brain.planning.arm_assignment_resolver.resolve_arms",
                        forbidden_assignment)
    before = session.scene.raw_document()
    expected = "extra_forbidden" if advertisement == "invalid" else "unsupported_protocol_version"
    with pytest.raises(ValueError, match=expected):
        session.process_turn("preflight-" + advertisement, task(arm=None))
    assert not calls
    assert not session.exported_commands
    assert session.scene.raw_document() == before


@pytest.mark.parametrize("mode", ["recipe", "qwen"])
def test_v3_only_contract_is_rejected_before_any_skill_planning(mode):
    session = setup(mode)
    session.pipeline.control_skill_contract["supported_protocols"] = ["3.0"]
    requests = []
    session.pipeline.skill_planner.provider = provider_for({"operations": []}, requests)
    recipe_calls = []
    session.pipeline.dual_skill_recipe = lambda request: recipe_calls.append(request)
    before = session.scene.raw_document()
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        session.process_turn("v3-only", task())
    assert not requests and not recipe_calls
    assert not session.exported_commands
    assert session.scene.raw_document() == before


def test_skill_model_cannot_change_the_grounded_source():
    session = setup()
    session.pipeline.dual_skill_recipe = lambda request: {"operations": [
        {"operation_id": request.operations[0].operation_id,
         "steps": [{"skill_name": "pick", "parameters": {"source": 8}}]}]}
    with pytest.raises(ValueError, match="object_binding_changed"):
        session.process_turn("changed", task())
    assert not session.exported_commands


@pytest.mark.parametrize("mode", ["recipe", "qwen"])
@pytest.mark.parametrize("skill", ["pour", "handover", "cooperative_grasp"])
def test_unregistered_cooperative_skill_never_exports_or_changes_runtime(mode, skill):
    """D14: neither planning route may invent a Control cooperative skill."""
    session = setup(mode)
    before_scene = session.scene.raw_document()
    before_arms = session.arm_states.model_dump(mode="json")
    draft = {"operations": [{"operation_id": "op-1", "steps": [
        {"skill_name": skill, "parameters": {"source": 7}}]}]}
    requests = []
    if mode == "qwen":
        session.pipeline.skill_planner.provider = provider_for(draft, requests)
    else:
        session.pipeline.dual_skill_recipe = lambda request: draft
    with pytest.raises(ValueError, match="control_skill_unregistered: " + skill):
        session.process_turn("unregistered-" + skill, task())
    assert not session.exported_commands
    assert session.pending_commands is None
    assert session.scene.raw_document() == before_scene
    assert session.arm_states.model_dump(mode="json") == before_arms
    if mode == "qwen":
        assert len(requests) == 1  # No hidden fallback to a registered pick.


def test_v4_qwen_uses_operation_local_schema_and_actual_skill_contract():
    session = setup("qwen")
    requests = []
    provider = provider_for({"operations": [{"operation_id": "op-1", "steps": [
        {"skill_name": "pick", "parameters": {"source": 7}}]}]}, requests)
    session.pipeline.skill_planner.provider = provider
    result = session.process_turn("qwen", task())
    assert len(requests) == 1
    assert provider.calls[0]["stage"] == "dual_operation_planning"
    assert result.commands.skill_contract_revision == "fixture-reviewed-v1"
    assert "fixture-reviewed-v1" in str(requests[0]["messages"])
    assert result.commands.commands[0].parameters == {"source": 7}


@pytest.mark.parametrize("fault", ["scene_version", "source", "arm", "dependency"])
def test_bound_planning_request_cannot_drift_from_grounded_task(fault):
    from robot_agent_brain.models.dual_operation_planning import DualOperationPlanningRequest
    session = setup()
    session.process_turn("bound", task())
    raw = session.pipeline.skill_planner.last_trace.context.model_dump(mode="python")
    if fault == "scene_version":
        raw["scene_version"] += 1
    else:
        field, value = {"source": ("source_object_id", 8), "arm": ("arm", "left"),
                        "dependency": ("depends_on", ["invented"])}[fault]
        raw["operations"][0][field] = value
    with pytest.raises(ValueError, match="binding_mismatch"):
        DualOperationPlanningRequest.model_validate(raw)


def test_runtime_hold_does_not_override_operation_arm_or_default():
    from robot_agent_brain.planning.arm_assignment_resolver import resolve_arms
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    session = setup()
    session.arm_states.arms["right"].holding_object = 7
    grounded = GroundedTask(instruction="放下苹果", scene_id=1, scene_version=1,
        entities=[{"entity_id": "a", "semantic_name": "apple", "category": "fruit", "scene_object_id": 7}],
        operations=[{"operation_id": "op-release", "task_type": "release", "target": "a"}])
    audit = []
    allocated = resolve_arms(grounded, session.robot_profiles.profiles["fixture_only"],
        runtime=session.arm_states, audit=audit)
    assert allocated.operations[0].arm == "left"
    assert audit[0]["source"] == "configured_default_arm"
    grounded.operations[0].arm = "left"
    explicit = resolve_arms(grounded, session.robot_profiles.profiles["fixture_only"], runtime=session.arm_states)
    assert explicit.operations[0].arm == "left"
    assert session.arm_states.arms["right"].holding_object == 7
