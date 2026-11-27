import pytest
from robot_agent_brain.contracts.camera import CameraFrame
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.planning.arm_assignment_resolver import resolve_arms
from robot_agent_brain.models.qwen_http import QwenProviderError
from test_dual_v4_pipeline import setup
from test_layout_qwen_planning import provider_for


def inputs():
    session = setup()
    task = GroundedTask(instruction="分别抓取", scene_id=session.scene.scene_id,
        scene_version=session.scene.scene_version,
        entities=[dict(entity_id=name, semantic_name=name, category="fruit", scene_object_id=identifier)
                  for name, identifier in [("apple", 7), ("banana", 8)]],
        operations=[dict(operation_id="op-a", task_type="grasp", target="apple", arm="left"),
                    dict(operation_id="op-b", task_type="grasp", target="banana")])
    frame = CameraFrame(camera_id="camera", scene_id=session.scene.scene_id,
        scene_version=session.scene.scene_version, scene_sub_version=session.scene.scene_sub_version,
        width=10, height=10, rgb=b"test-transport-image",
        instance_boxes=[dict(scene_object_id=identifier, bbox=(i * 100, 0, i * 100 + 50, 50))
                        for i, identifier in enumerate([2, 3, 7, 8])])
    return session, task, frame


def output():
    return {"status": "assigned", "assignments": [
        {"operation_id": "op-a", "arm": "left"}, {"operation_id": "op-b", "arm": "right"}],
        "arm_order": {"left": ["op-a"], "right": ["op-b"]}}


def allocate(session, task, frame, provider, audit=None):
    return resolve_arms(task, session.robot_profiles.profiles["fixture_only"],
        runtime=session.arm_states, arm_usage="both_required", scene=session.scene,
        capture=lambda: frame, model_provider=provider, audit=audit)


def test_partial_locks_and_real_provider_request_are_checked():
    session, task, frame = inputs()
    requests, audit = [], []
    provider = provider_for(output(), requests)
    result = allocate(session, task, frame, provider, audit)
    assert len(requests) == 1
    assert provider.calls[0]["stage"] == "arm_assignment"
    assert [op.arm for op in result.operations] == ["left", "right"]
    assert [item["source"] for item in audit] == ["explicit_arm", "visual_assignment"]
    assert requests[0]["messages"][-1]["content"][-1]["type"] == "image_url"
    assert task.operations[1].arm is None


def test_fully_locked_tasks_skip_camera_and_model():
    session, task, frame = inputs()
    task.operations[1].arm = "right"
    class Forbidden:
        def assign_arms(self, request):
            raise AssertionError("model not needed")
    def capture():
        raise AssertionError("camera not needed")
    result = resolve_arms(task, session.robot_profiles.profiles["fixture_only"],
        runtime=session.arm_states, arm_usage="both_required", model_provider=Forbidden(),
        scene=session.scene, capture=capture)
    assert [op.arm for op in result.operations] == ["left", "right"]


@pytest.mark.parametrize("field", ["same_arm_group", "parallel_group", "parallel_required"])
def test_retired_assignment_constraints_rejected_at_semantic_boundary(field):
    from robot_agent_brain.models.task_understanding import TaskParseWireOutput
    data = {"status": "accepted", "turn_kind": "robot_task",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "operations": [{"operation": "grasp", "target": "apple", field: None}]}
    with pytest.raises(ValueError):
        TaskParseWireOutput.model_validate(data)


def test_visual_assignment_request_contains_no_same_arm_groups():
    session, task, frame = inputs()
    captured = []
    class Provider:
        def assign_arms(self, request):
            captured.append(request.model_dump(mode="json"))
            return output()
    result = allocate(session, task, frame, Provider())
    assert "same_arm_groups" not in captured[0]
    assert [op.arm for op in result.operations] == ["left", "right"]


@pytest.mark.parametrize("field", ["scene_id", "scene_version", "scene_sub_version"])
def test_stale_frame_never_calls_assignment_or_uses_fallback(field):
    session, task, frame = inputs()
    frame = frame.model_copy(update={field: getattr(frame, field) + 1})
    requests = []
    with pytest.raises(ValueError, match="frame_scene_mismatch"):
        allocate(session, task, frame, provider_for(output(), requests))
    assert not requests


def test_insufficient_model_evidence_is_audited_fallback_not_visual_success():
    session, task, frame = inputs()
    requests, audit = [], []
    provider = provider_for({"status": "insufficient_evidence", "assignments": [], "arm_order": {}}, requests)
    result = allocate(session, task, frame, provider, audit)
    assert [op.arm for op in result.operations] == ["left", "right"]
    assert audit[1]["source"] == "deterministic_balanced_fallback"
    assert audit[1]["model_status"] == "insufficient_evidence"


def test_model_cannot_override_explicit_arm_and_get_silently_repaired():
    session, task, frame = inputs()
    value = output()
    value["assignments"][0]["arm"] = "right"
    value["arm_order"] = {"left": [], "right": ["op-a", "op-b"]}
    requests = []
    with pytest.raises(QwenProviderError, match="locked_arm_changed"):
        allocate(session, task, frame, provider_for(value, requests))
    assert len(requests) == 1


def test_missing_arm_identity_does_not_use_image_left_as_robot_left():
    session, task, frame = inputs()
    frame.instance_boxes = frame.instance_boxes[1:]
    requests, audit = [], []
    allocate(session, task, frame, provider_for(output(), requests), audit)
    assert not requests
    assert audit[1]["source"] == "deterministic_balanced_fallback"


def test_no_evidence_and_no_declared_fallback_requests_arm_clarification():
    from robot_agent_brain.errors import BrainIssue
    from robot_agent_brain.scene.user_feedback import explain_issue
    session, task, frame = inputs()
    profile = session.robot_profiles.profiles["fixture_only"].model_copy(update={"default_task_arm": None})
    requests = []
    provider = provider_for({"status": "insufficient_evidence", "assignments": [], "arm_order": {}}, requests)
    with pytest.raises(ValueError, match="arm_assignment_insufficient_evidence") as caught:
        resolve_arms(task, profile, runtime=session.arm_states, scene=session.scene,
            model_provider=provider, capture=lambda: frame)
    issue = BrainIssue(code="arm_assignment_insufficient_evidence", message=str(caught.value), stage="planning")
    explain_issue(issue, caught.value, session.scene, session.pipeline.assets)
    assert "左臂" in issue.clarification_question
    assert len(requests) == 1


def test_session_calls_assignment_before_v4_skills_and_preserves_runtime():
    from robot_agent_brain.contracts.task_intent import TaskIntent
    from robot_agent_brain.contracts.turn import BrainTurn
    session, task, frame = inputs()
    calls = []
    class Provider:
        def assign_arms(self, request):
            calls.append("assignment")
            assert request.operations[0].locked_arm == "left"
            return output()
        def plan_dual_operations(self, request):
            calls.append("skills")
            assert [op.arm for op in request.operations] == ["left", "right"]
            return {"operations": [{"operation_id": op.operation_id, "steps": [
                {"skill_name": "pick", "parameters": {"source": op.source_object_id}}]}
                for op in request.operations]}
    session.pipeline.skill_planner.mode = "qwen"
    session.pipeline.skill_planner.provider = Provider()
    session.capture = lambda: frame
    intent = TaskIntent(instruction=task.instruction, arm_usage="both_required",
        entities=[{"entity_id": e.entity_id, "semantic_name": e.semantic_name, "category": e.category}
                  for e in task.entities], operations=task.operations)
    before = session.arm_states.model_dump()
    result = session.process_turn("visual-plan", BrainTurn(status="accepted", turn_kind="robot_task",
        instruction=task.instruction, task_intent=intent))
    assert calls == ["assignment", "skills"]
    assert [c.arm for c in result.commands.commands] == ["left", "right"]
    assert [c.parameters["source"] for c in result.commands.commands] == [7, 8]
    assert session.arm_states.model_dump() == before
