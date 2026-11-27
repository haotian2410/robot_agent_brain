import pytest

from robot_agent_brain.models.failure_context import (
    FailureContextAmendment, FailureContextDecision, FailureContextRequest,
)
from robot_agent_brain.session.conversation_memory import ConversationMemory, ConversationTurn, SelectionDecision
from robot_agent_brain.session.conversation_journal import ConversationJournal
from robot_agent_brain.semantics.recovery_guard import validate_recovery_decision, validate_recovery_scope
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation, TaskType
from robot_agent_brain.session.conversation_memory import (
    FailureChain, FailureChainState, StepLedgerEntry, SemanticDraft,
)
from robot_agent_brain.web.service import AgentService
from robot_agent_brain.grounding.ambiguity_policy import AmbiguityPolicy, AmbiguityRequiresClarification
from types import SimpleNamespace


def test_failure_context_schema_is_payload_free_for_ask_user():
    decision = FailureContextDecision(
        decision="ask_user", source_turn_id="web-1", question="请说明参照物。"
    )
    assert decision.resolved_instruction is None
    with pytest.raises(ValueError, match="ask_user_payload_invalid"):
        FailureContextDecision(
            decision="ask_user", source_turn_id="web-1", question="q",
            amendments=[{"subject_role": "x", "field": "color", "value": "red"}],
        )


def test_failure_chain_is_bounded_to_five_user_turns():
    memory = ConversationMemory()
    for index in range(5):
        turn = ConversationTurn(
            turn_id=f"t{index}", session_id="s", sequence=index + 1,
            raw_user_text="retry", final_outcome="clarification_required",
        )
        memory.begin_failure(turn)
    assert memory.active_failure_chain.failed_user_turn_count == 5
    assert memory.active_failure_chain.state.value == "exhausted"


def test_recovery_guard_cannot_amend_completed_step_or_unknown_source():
    decision = FailureContextDecision(
        decision="revise_task", source_turn_id="t1", target_step_id="step-1", resolved_instruction="补充目标"
    )
    with pytest.raises(ValueError, match="completed_step_immutable"):
        validate_recovery_decision(decision, root_failure_turn_id="t1",
                                   known_turn_ids={"t1"}, completed_step_ids={"step-1"},
                                   allowed_actions={"revise_task"})
    decision = FailureContextDecision(
        decision="revise_task", source_turn_id="unknown", resolved_instruction="x"
    )
    with pytest.raises(ValueError, match="source_turn_unknown"):
        validate_recovery_decision(decision, root_failure_turn_id="t1",
                                   known_turn_ids={"t1"}, allowed_actions={"revise_task"})


def test_failure_context_request_is_independent_and_strict():
    request = FailureContextRequest(current_user_text="补充参照物", root_failure_turn_id="t1")
    assert request.protocol_version == "failure_context.v1"
    with pytest.raises(ValueError):
        FailureContextRequest(current_user_text="x", root_failure_turn_id="t1", history=[{"bad": 1}])


def test_late_fact_revises_same_turn_without_new_user_count(tmp_path):
    memory = ConversationMemory()
    turn = ConversationTurn(turn_id="t1", session_id="s", sequence=1,
                            raw_user_text="移动苹果", final_outcome="failed")
    memory.begin_failure(turn)
    memory.revise_turn("t1", final_outcome="scene_updated", executed=True)
    assert len(memory.recent_turns) == 1
    assert memory.recent_turns[0].finalization_revision == 2
    assert memory.active_failure_chain.failed_user_turn_count == 1
    path = ConversationJournal(tmp_path).write("t1", {"ok": True})
    assert path.exists()


def test_auto_selection_decision_is_persisted_on_failure_chain():
    memory = ConversationMemory()
    turn = ConversationTurn(turn_id="t1", session_id="s", sequence=1,
                            raw_user_text="把一个苹果移动", final_outcome="clarification_required",
                            auto_selection_decisions=[SelectionDecision(
                                entity_role="apple", chosen_ids=[7], candidate_ids=[7, 9],
                                decision_key="k", policy="auto")])
    chain = memory.begin_failure(turn)
    chain.selection_decisions = list(turn.auto_selection_decisions)
    assert chain.selection_decisions[0].chosen_ids == [7]


def test_recovery_scope_rejects_authority_amendments():
    decision = FailureContextDecision(decision="revise_task", source_turn_id="t1",
                                      resolved_instruction="换成另一个目标", scope="new_task")
    with pytest.raises(ValueError, match="scope_new_task_mismatch"):
        validate_recovery_scope(decision, root_instruction="把苹果放进篮子")


def test_u_payload_that_drops_recovery_color_is_rejected_before_side_effects():
    turn = BrainTurn(status="accepted", turn_kind="robot_task", instruction="把苹果放进篮子",
                     task_intent=TaskIntent(instruction="把苹果放进篮子", entities=[
                         TaskEntity(entity_id="apple", semantic_name="apple", category="fruit"),
                         TaskEntity(entity_id="basket", semantic_name="basket", category="container")],
                         operations=[Operation(operation_id="op-1", task_type=TaskType.PICK_AND_PLACE,
                                               source="apple", destination="basket",
                                               placement_target={"kind": "container_interior", "reference": "basket"})]))
    with pytest.raises(ValueError, match="u_condition_lost:color"):
        BrainApplication._validate_recovery_u_conditions(turn, {
            "accepted_amendments": [{"field": "color", "value": "blue"}]
        })


def test_recovery_cannot_drift_to_original_scene_without_user_request():
    decision = FailureContextDecision(decision="revise_task", source_turn_id="t1",
                                      resolved_instruction="在原始场景中增加一个苹果")
    with pytest.raises(ValueError, match="scene_basis_drift"):
        validate_recovery_scope(decision, root_instruction="增加一个苹果",
                                current_user_text="把它改成蓝色")


def test_recovery_inherits_explicit_original_authority_from_same_failure_chain():
    decision = FailureContextDecision(decision="continue_task", source_turn_id="t1",
        resolved_instruction="在原始场景中把最左边的苹果改成蓝色")
    assert validate_recovery_scope(decision,
        root_instruction="在原始场景中把苹果改成蓝色", current_user_text="最左边的") is decision


def test_new_task_does_not_inherit_original_authority_from_old_chain():
    decision = FailureContextDecision(decision="new_task", scope="new_task", source_turn_id="t1",
        resolved_instruction="在原始场景中增加一个苹果")
    with pytest.raises(ValueError, match="scene_basis_drift"):
        validate_recovery_scope(decision, root_instruction="在原始场景中改色",
                                current_user_text="增加一个苹果")


def test_model_draft_cannot_grant_original_authority():
    decision = FailureContextDecision(decision="continue_task", source_turn_id="t1",
        resolved_instruction="在原始场景中把最左边的苹果改成蓝色")
    with pytest.raises(ValueError, match="scene_basis_drift"):
        validate_recovery_scope(decision, root_instruction="把苹果改成蓝色",
            latest_task_draft={"canonical_turn":{"scene_basis":"original"}},
            current_user_text="最左边的")


@pytest.mark.parametrize("text", ["最左边那个。", "最左边那个苹果。", "左边的苹果。",
    "右边那个篮子。", "不对，改成右边的苹果。", "换成托盘。", "那两个苹果都要。"])
def test_selector_supplement_stays_on_recovery_route(text):
    from robot_agent_brain.semantics.recovery_routing import continuation_candidate
    assert continuation_candidate(text)


@pytest.mark.parametrize("text", ["把左边的苹果放进篮子。", "有几个香蕉？", "拉开抽屉",
    "不放了，改为把最左边的苹果改成蓝色。"])
def test_complete_action_is_not_a_selector_supplement(text):
    from robot_agent_brain.semantics.recovery_routing import continuation_candidate
    assert not continuation_candidate(text)


def test_recovery_source_selection_maps_to_scene_edit_target():
    from robot_agent_brain.contracts.turn import SceneEditPlan, SceneEditIntent
    plan=SceneEditPlan(entities=[TaskEntity(entity_id="apple",semantic_name="apple",category="fruit")],
        operations=[SceneEditIntent(operation="translate",target="apple",direction="right",distance_m=.05)],
        relations=[{"subject":"apple","relation":"leftmost"}])
    turn=BrainTurn(turn_kind="scene_edit",status="accepted",instruction="把最左边的苹果向右移动5厘米",scene_edit=plan)
    BrainApplication._validate_recovery_u_conditions(turn,{"accepted_amendments":[
        {"subject_role":"source","field":"selection","value":"leftmost"}]})


@pytest.mark.parametrize("destination,accepted", [("tray", True),("apple", False)])
def test_recovery_chinese_destination_matches_canonical_asset_only_in_correct_role(destination,accepted):
    turn=SimpleNamespace(task_intent=SimpleNamespace(
        entities=[SimpleNamespace(entity_id=n,semantic_name=n) for n in ("apple","tray")],
        operations=[SimpleNamespace(source="tray" if destination=="apple" else "apple",destination=destination)],
        spatial_relations=[]))
    evidence={"accepted_amendments":[{"subject_role":"destination","field":"target","value":"托盘"}]}
    if accepted: BrainApplication._validate_recovery_u_conditions(turn,evidence,aliases={"托盘":"tray"})
    else:
        with pytest.raises(ValueError,match="u_condition_lost:target"):
            BrainApplication._validate_recovery_u_conditions(turn,evidence,aliases={"托盘":"tray"})


def test_recovered_composite_skips_completed_prefix_and_runs_only_suffix():
    """A recovered full decomposition must not replay already committed steps."""
    class FakeService:
        _run_steps = AgentService._run_steps
        MAX_STEP_ATTEMPTS = 5
        RETRYABLE_EXECUTION_CODES = set()
        _retry_allowed = staticmethod(AgentService._retry_allowed)
        verdict = staticmethod(AgentService.verdict)

        def __init__(self):
            self.progress = {}
            self.calls = []
            self.app = SimpleNamespace(_save_session=lambda _session_id: None)

        def _run_step(self, session, platform, request, identifier, instruction, **kwargs):
            self.calls.append(instruction)
            return (SimpleNamespace(request_id="new-child"),
                    {"outcome": "answered", "executed": False, "artifacts": []}, [])

        def composite_result(self, records, results, steps):
            return {"records": records, "results": results}

    session = SimpleNamespace(
        conversation_memory=SimpleNamespace(
            active_failure_chain=FailureChain(
                chain_id="c1", root_failure_turn_id="t1", root_instruction="两步任务",
                state=FailureChainState.WAITING_USER,
                step_ledger=[StepLedgerEntry(
                    step_id="step-1", original_step_index=1,
                    instruction="第一步", status="committed", request_ids=["old-child"])])),
        last_recovery_evidence={"scope": "remaining_steps"},
        pending_step_ledger=[],
        scene=None,
    )
    request = SimpleNamespace(sessionID="s")
    platform = SimpleNamespace(receipts=[])
    from robot_agent_brain.contracts.decomposition import Subtask
    steps = [Subtask(kind="scene_edit", instruction="第一步"),
             Subtask(kind="scene_query", instruction="第二步")]

    service = FakeService()
    result, _ = service._run_steps(session, platform, request, "task-2", steps)

    assert service.calls == ["第二步"]
    assert result["records"][0]["reused"] is True
    assert result["records"][0]["request_id"] == "old-child"
    assert result["records"][1]["instruction"] == "第二步"


def test_recovery_amendments_are_kept_in_semantic_draft_before_u(tmp_path):
    class RecoveryProvider:
        def recover_failure(self, payload):
            return FailureContextDecision(
                decision="revise_task", source_turn_id="t1",
                resolved_instruction="把苹果改成蓝色并放进篮子",
                amendments=[FailureContextAmendment(
                    subject_role="apple", field="color", value="blue",
                    evidence={"turn_id": "t2"})])

    memory = ConversationMemory()
    root = ConversationTurn(turn_id="t1", session_id="s", sequence=1,
                            raw_user_text="把苹果放进篮子", final_outcome="clarification_required")
    memory.begin_failure(root, draft=SemanticDraft(
        source_request_id="t1", validity="partial_semantics", unresolved_slots=["color"]))
    session = SimpleNamespace(conversation_memory=memory, last_recovery_evidence=None, scene=None)
    service = object.__new__(AgentService)
    service.output = tmp_path
    service.config = SimpleNamespace(conversation_recovery_enabled=True,
                                     conversation_recovery_max_failed_user_turns=5,
                                     conversation_recovery_max_input_chars=48000)
    service.app = SimpleNamespace(provider=RecoveryProvider())
    request = SimpleNamespace(sessionID="s", clientRequestID="t2", command="改成蓝色")

    assert service._maybe_recover(session, request) == "把苹果改成蓝色并放进篮子"
    draft = memory.active_failure_chain.semantic_draft
    assert draft.validity == "partial_semantics"
    assert "color" in draft.known_fields
    assert draft.canonical_turn["effective_instruction"] == "把苹果改成蓝色并放进篮子"
    assert draft.field_provenance[0]["source_turn_id"] == "t2"
    assert draft.field_provenance[0]["subject_role"] == "apple"
    import json
    audit = json.loads(next((tmp_path / "s/conversation/recovery").glob("*.json")).read_text())
    assert audit["request"]["current_user_text"] == "改成蓝色"
    assert audit["client_request_id"] == "t2"
    assert draft.execution_authority == "none"


def test_no_failure_chain_does_not_call_recovery_provider():
    class RaisingProvider:
        def recover_failure(self, _payload):
            raise AssertionError("R must not run on a normal turn")

    service = object.__new__(AgentService)
    service.config = SimpleNamespace(conversation_recovery_enabled=True,
                                     conversation_recovery_max_failed_user_turns=5,
                                     conversation_recovery_max_input_chars=48000)
    service.app = SimpleNamespace(provider=RaisingProvider())
    session = SimpleNamespace(conversation_memory=ConversationMemory(), scene=None,
                              last_recovery_evidence=None)
    request = SimpleNamespace(sessionID="s", clientRequestID="normal-1", command="有几个苹果？")

    assert service._maybe_recover(session, request) == request.command


def test_exhausted_failure_chain_does_not_start_a_new_recovery_round():
    class RaisingProvider:
        def recover_failure(self, _payload):
            raise AssertionError("exhausted chains must not call R")

    memory = ConversationMemory()
    for index in range(5):
        memory.begin_failure(ConversationTurn(
            turn_id=f"t{index}", session_id="s", sequence=index + 1,
            raw_user_text="把苹果放进托盘", final_outcome="clarification_required"))
    service = object.__new__(AgentService)
    service.config = SimpleNamespace(conversation_recovery_enabled=True,
                                     conversation_recovery_max_failed_user_turns=5,
                                     conversation_recovery_max_input_chars=48000)
    service.app = SimpleNamespace(provider=RaisingProvider())
    session = SimpleNamespace(conversation_memory=memory, scene=None,
                              last_recovery_evidence=None)
    request = SimpleNamespace(sessionID="s", clientRequestID="t5", command="那个")

    result = service._maybe_recover(session, request)
    assert result["outcome"] == "failed"
    assert result["error"]["code"] == "conversation_recovery_exhausted"


def test_ambiguity_policy_defaults_to_question_and_auto_resolve_is_narrow():
    candidates = [11, 17]
    common = dict(session_id="s", logical_task_id="task", step_id="step-1",
                  role="apple", revision=1, scene_digest="scene")
    with pytest.raises(AmbiguityRequiresClarification):
        AmbiguityPolicy().choose(candidates, **common)

    policy = AmbiguityPolicy(prefer_auto_resolve=True)
    first = policy.choose(candidates, **common)
    second = policy.choose(list(reversed(candidates)), **common)
    assert first.chosen_ids == second.chosen_ids
    assert first.candidate_ids == [11, 17]

    with pytest.raises(AmbiguityRequiresClarification):
        policy.choose(candidates, **common, destination=True)
    with pytest.raises(AmbiguityRequiresClarification):
        policy.choose(candidates, **common, destructive=True)
    with pytest.raises(AmbiguityRequiresClarification):
        policy.choose(candidates, **common,
                      evidence={"color_evidence_status": "unverifiable_fallback"})
    verified = policy.choose(candidates, **common,
                             evidence={"color_evidence_status": "verified"})
    assert verified.color_evidence_status == "verified"


def test_ambiguity_policy_never_overrides_explicit_id():
    decision = AmbiguityPolicy(prefer_auto_resolve=True).choose(
        [11, 17], session_id="s", logical_task_id="task", step_id="step-1",
        role="apple", revision=1, scene_digest="scene", explicit=17)
    assert decision.chosen_ids == [17]
