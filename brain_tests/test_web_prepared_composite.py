"""Browser transaction orchestration with one U, no live Control execution."""
from types import SimpleNamespace
import pytest
from robot_agent_brain.contracts.composite_turn import CompositeTask
from robot_agent_brain.contracts.decomposition import TaskDecomposition
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.web.service import AgentService
from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
from test_composite_orchestrator import LEFT, place_on_table, commits
from test_web_gateway import Browser, adapter


class Unified:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail
        self.understandings = 0
        self.task = CompositeTask(instruction="先移动苹果然后搬到桌面", phases=[LEFT, place_on_table()])

    def decompose(self, request):
        return TaskDecomposition(steps=[{"kind": p.turn_kind.value, "instruction": p.instruction}
                                        for p in self.task.phases])

    def understand_composite(self, request):
        self.understandings += 1
        if self.fail:
            raise ValueError("provider_output_schema_invalid: phases")
        return self.task

    def understand_turn(self, request):
        raise AssertionError("prepared phase must not call U again")


def run(tmp_path, provider, *, scene=None, service_class=AgentService):
    browser = Browser(scene=scene)
    service = service_class(BrainConfig(provider="replay", planner="recipe", scene_id_bits=32,
        scene_platform_object_ids={0}, output_dir=str(tmp_path), debug=True), provider=provider,
        platform_factory=lambda binding: adapter(browser, tmp_path / binding["id"] / "gateway_transactions"))
    session_id = service.activate(SessionRequest(browserID="b"))["sessionID"]
    record, _ = service.tasks.submit(StartTask(command=provider.task.instruction, scene=browser.scene,
        sessionID=session_id, clientRequestID="unified", browserID="b", sceneDigest=digest(browser.scene)))
    before = digest(browser.scene)
    service.execute(record["id"])
    return SimpleNamespace(service=service, browser=browser, session_id=session_id, before=before,
                           result=service.tasks.get(record["id"])["result"])


def test_web_one_u_commits_scene_then_plans_and_persists_semantics(tmp_path):
    checkpoints = []
    class InspectCheckpoint(AgentService):
        def _run_step(self, session, platform, request, identifier, instruction, **kwargs):
            state = self.app.store.load(request.sessionID)
            checkpoints.append([item.model_copy(deep=True) for item in state.pending_step_ledger])
            return super()._run_step(session, platform, request, identifier, instruction, **kwargs)

    provider = Unified()
    case = run(tmp_path, provider, service_class=InspectCheckpoint)
    assert provider.understandings == 1
    assert case.result["outcome"] == "scene_updated", case.result
    assert case.result["metrics"]["steps"][-1]["outcome"] == "plan_ready"
    assert case.result["executed"] is False
    assert case.result["metrics"]["understanding_calls"] == 1
    assert commits(case.browser) == 1
    session = case.service.app.get_session(case.session_id)
    ledger = session.conversation_memory.recent_turns[-1].step_ledger
    assert [s.status for s in ledger] == ["committed", "plan_ready_unexecuted"]
    assert all(s.canonical_turn is not None for s in ledger)
    assert ledger[0].understanding_evidence["canonical_task"]["phases"][1]["turn_kind"] == "robot_task"
    assert ledger[0].scene_after == ledger[1].scene_before
    assert ledger[1].scene_before == ledger[1].scene_after
    assert [item.status for item in checkpoints[0]] == ["processing", "planned"]
    assert [item.status for item in checkpoints[1]] == ["committed", "processing"]
    assert checkpoints[0][0].understanding_evidence is not None
    assert all(item.canonical_turn for item in checkpoints[0])
    # Reload from persisted state, not the process-local session cache.
    case.service.app.sessions.pop(case.session_id)
    restored = case.service.app.get_session(case.session_id)
    restored_ledger = restored.conversation_memory.recent_turns[-1].step_ledger
    assert restored_ledger == ledger


def test_invalid_composite_does_not_fallback_or_apply_first_phase(tmp_path):
    provider = Unified(fail=True)
    case = run(tmp_path, provider)
    assert provider.understandings == 1
    assert case.result["outcome"] == "failed"
    assert commits(case.browser) == 0
    assert digest(case.browser.scene) == case.before


def test_prepared_payload_cannot_enter_external_application_route(tmp_path):
    provider = Unified()
    case = run(tmp_path, provider)
    with pytest.raises(ValueError, match="prepared_turn_internal_only"):
        case.service.app.handle(LEFT.instruction, session_id=case.session_id, prepared_turn=LEFT)


def test_layout_phase_publishes_new_objects_before_robot_plan(tmp_path):
    from test_layout_transaction import setup
    from robot_agent_brain.contracts.turn import BrainTurn
    scene, spec, _ = setup()
    spec = spec.model_copy(update={"items": spec.items.model_copy(update={"requested_count": 1}),
                                   "pattern": spec.pattern.model_copy(update={"rows": 1, "cols": 1})})
    provider = Unified()
    provider.task = CompositeTask(instruction="排列一个苹果然后放到桌面", phases=[
        BrainTurn(status="accepted", turn_kind="scene_layout", instruction="排列一个苹果", arrangement_spec=spec),
        place_on_table()])
    case = run(tmp_path, provider, scene=scene)
    assert provider.understandings == 1
    assert case.result["metrics"]["steps"][-1]["outcome"] == "plan_ready", case.result
    assert commits(case.browser) == 1
    session = case.service.app.get_session(case.session_id)
    assert len(session.scene.objects) == 2
    assert session.composite_turn_records[-1]["phases"][0]["scene_digest_after"] == session.composite_turn_records[-1]["phases"][1]["scene_digest_before"]


def test_robot_binding_failure_keeps_edit_and_complete_semantic_ledger(tmp_path):
    provider = Unified()
    robot = place_on_table().model_copy(deep=True)
    robot.task_intent.entities[0].semantic_name = "not_in_scene"
    provider.task = CompositeTask(instruction=provider.task.instruction, phases=[LEFT, robot])
    case = run(tmp_path, provider)
    assert provider.understandings == 1
    assert commits(case.browser) == 1
    assert digest(case.browser.scene) != case.before
    assert case.result["metrics"]["steps"][-1]["state"] == "stopped"
    session = case.service.app.get_session(case.session_id)
    ledger = session.conversation_memory.recent_turns[-1].step_ledger
    assert ledger[0].status == "committed"
    assert ledger[1].status in {"clarification", "rejected"}
    assert session.conversation_memory.active_failure_chain.step_ledger == ledger
    assert ledger[1].scene_before == ledger[1].scene_after
