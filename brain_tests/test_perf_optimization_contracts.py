"""Performance changes may improve model prompts, never relax output contracts."""
import hashlib
import json
from pathlib import Path

import pytest

from robot_agent_brain.models.prompts import build_atomic_skill_prompt
from robot_agent_brain.models.qwen_http import QwenProviderError
from test_skill_planning_atomic_qwen import commands, context, provider_for, assembly_guard


def test_s_draft_appendix_follows_unmodified_control_semantics(tmp_path):
    source = "# Control skills\nKeep all skill semantics.\n"
    path = tmp_path / "skill.md"
    path.write_text(source)
    prompt, sha = build_atomic_skill_prompt(path)
    assert prompt.startswith(source)
    assert sha == hashlib.sha256(source.encode()).hexdigest()
    assert "Brain 规划阶段专用输出格式" in prompt
    assert prompt.index("Brain 规划阶段专用输出格式") > prompt.index("Brain 校验器实际接受")
    for key in ("schema_version", "request_id", "scene_id", "scene_version", "metadata", "explanation"):
        assert key in prompt
    assert path.read_text() == source


@pytest.mark.parametrize("field,value", [("schema_version","2.0"),("request_id","bad"),
    ("scene_id",3),("scene_version",1),("metadata",{}),("explanation","ignored?")])
def test_s_extra_root_fields_still_fail_both_attempts(field, value):
    answer = json.dumps({**commands(),field:value})
    provider, requests = provider_for([answer,answer])
    with pytest.raises(QwenProviderError) as error:
        provider.plan_atomic(context(),validate=assembly_guard())
    assert error.value.code == "skill_plan_output_invalid"
    assert len(requests) == 2
    assert all(c["status"] == "failed" for c in provider.calls)


def test_s_valid_draft_first_pass_and_invalid_then_valid_remain_supported():
    good = json.dumps(commands())
    provider, requests = provider_for([good])
    assert len(provider.plan_atomic(context(),validate=assembly_guard()).commands) == 8
    assert len(requests) == 1
    provider, requests = provider_for([json.dumps({**commands(),"scene_id":3}),good])
    assert len(provider.plan_atomic(context(),validate=assembly_guard()).commands) == 8
    assert len(requests) == 2
    assert [c["status"] for c in provider.calls] == ["failed","succeeded"]


def test_recovery_prompt_examples_match_strict_wire_schema():
    from robot_agent_brain.models.failure_context import FailureContextDecision
    import robot_agent_brain.models.prompts as prompts
    path = Path(prompts.__file__).parent / "prompt_templates/failure_context_v1.txt"
    examples = [json.loads(line) for line in path.read_text().splitlines()
                if line.startswith('{"protocol_version"')]
    assert {x["decision"] for x in examples} == {
        "continue_task", "revise_task", "new_task", "ask_user", "cancel_chain"}
    for example in examples:
        example["source_turn_id"] = "actual-root-turn"
        FailureContextDecision.model_validate(example)


def test_recovery_revise_missing_instruction_remains_rejected():
    from robot_agent_brain.models.failure_context import FailureContextDecision
    with pytest.raises(ValueError, match="resolved_instruction_required"):
        FailureContextDecision(decision="revise_task", source_turn_id="real-turn")


@pytest.mark.parametrize("text", ["左边的", "右边那个", "ID 17 的", "红色的", "算了"])
def test_finite_recovery_candidates(text):
    from robot_agent_brain.semantics.recovery_routing import continuation_candidate
    assert continuation_candidate(text)


@pytest.mark.parametrize("text", ["删除它", "把它放进去", "桌面有几个香蕉", "增加苹果", "x"])
def test_routing_hint_does_not_guess_actions(text):
    from robot_agent_brain.semantics.recovery_routing import continuation_candidate
    assert not continuation_candidate(text)


def recovery_service_fixture(command="左边的", state="waiting_user", new_task=False):
    from types import SimpleNamespace as NS
    from robot_agent_brain.models.failure_context import FailureContextDecision
    from robot_agent_brain.session.conversation_memory import ConversationMemory, ConversationTurn
    from robot_agent_brain.web.service import AgentService
    memory = ConversationMemory()
    memory.begin_failure(ConversationTurn(turn_id="t1", session_id="s", sequence=1,
        raw_user_text="把苹果放到篮子里", final_outcome="clarification_required"))
    memory.active_failure_chain.state = type(memory.active_failure_chain.state)(state)
    calls = []
    def preview(*args, **kwargs):
        calls.append("U")
        return NS(status="accepted", scene_query=NS(query_type="count"))
    def recover(payload):
        calls.append("R")
        return FailureContextDecision(decision="ask_user", source_turn_id="t1", question="哪个苹果？")
    service = object.__new__(AgentService)
    service.config = NS(conversation_recovery_enabled=True,
        conversation_recovery_max_failed_user_turns=5, conversation_recovery_max_input_chars=20000)
    service.app = NS(pipeline=NS(understand_turn=preview), provider=NS(recover_failure=recover))
    session = NS(conversation_memory=memory, scene=None, dialogue=None)
    request = NS(command=command, sessionID="s", clientRequestID="t2", new_task=new_task)
    return service, session, request, calls


def test_short_ask_user_calls_only_r_no_preview():
    service, session, request, calls = recovery_service_fixture()
    result = service._maybe_recover(session, request)
    assert result["outcome"] == "clarification_required"
    assert calls == ["R"]


def test_complete_new_task_keeps_preview_and_supersedes():
    service, session, request, calls = recovery_service_fixture("桌面有几个香蕉")
    assert service._maybe_recover(session, request) == request.command
    assert calls == ["U"]
    assert session.conversation_memory.active_failure_chain.state.value == "superseded"


def test_exhausted_short_reply_has_zero_model_calls():
    service, session, request, calls = recovery_service_fixture(state="exhausted")
    assert service._maybe_recover(session, request)["error"]["code"] == "conversation_recovery_exhausted"
    assert calls == []


def test_exhausted_chain_still_allows_complete_new_task():
    service, session, request, calls = recovery_service_fixture("桌面有几个香蕉", state="exhausted")
    assert service._maybe_recover(session, request) == request.command
    assert calls == ["U"]


def test_explicit_new_task_has_no_recovery_or_preview():
    service, session, request, calls = recovery_service_fixture("桌面有几个香蕉", new_task=True)
    assert service._maybe_recover(session, request) == request.command
    assert calls == []


def test_partial_execution_never_enters_preview_or_r():
    from robot_agent_brain.session.conversation_memory import StepLedgerEntry
    service,session,request,calls=recovery_service_fixture()
    session.conversation_memory.active_failure_chain.step_ledger=[StepLedgerEntry(
        step_id="already-executed",original_step_index=1,instruction="抓取苹果",
        status="executed_confirmed",confirmed_effects=["pick confirmed"])]
    result=service._maybe_recover(session,request)
    assert result["error"]["code"]=="execution_partial_requires_new_task"
    assert calls==[]


def test_invalid_r_instruction_is_rejected_without_followup_u():
    from robot_agent_brain.models.failure_context import FailureContextDecision
    service,session,request,calls=recovery_service_fixture()
    def invalid(payload):
        calls.append("R")
        return FailureContextDecision(decision="revise_task",source_turn_id="t1")
    service.app.provider.recover_failure=invalid
    result=service._maybe_recover(session,request)
    assert result["error"]["code"]=="failure_context_invalid"
    assert "resolved_instruction_required" in result["error"]["message"]
    assert calls==["R"] and session.scene is None
    assert result["executed"] is False


@pytest.mark.parametrize("new_task", [False, True])
def test_reconciliation_prevents_all_model_calls_even_explicit_new_task(new_task):
    service, session, request, calls = recovery_service_fixture(
        "桌面有几个香蕉", state="blocked_reconciliation", new_task=new_task)
    assert service._maybe_recover(session, request)["error"]["code"] == "conversation_recovery_blocked"
    assert calls == []


@pytest.mark.parametrize("fault",["sync_unknown","lease_unknown","pending_execution"])
@pytest.mark.parametrize("enabled",[False,True])
def test_unknown_runtime_state_blocks_before_any_preview_or_recovery(fault,enabled):
    from types import SimpleNamespace as NS
    service,session,request,calls=recovery_service_fixture("桌面有几个香蕉",new_task=True)
    service.config.conversation_recovery_enabled=enabled
    if fault=="sync_unknown":
        session.sync_state="unknown"
    elif fault=="lease_unknown":
        session.platform=NS(lease_uncertain=True)
    else:
        session.pending_execution_request="unfinished-control"
    result=service._maybe_recover(session,request)
    assert result["outcome"]=="failed" and result["executed"] is False
    assert calls==[]
    assert session.conversation_memory.active_failure_chain.state.value=="waiting_user"


def test_unsupported_operation_amendment_without_evidence_is_rejected():
    from robot_agent_brain.models.failure_context import FailureContextDecision
    from robot_agent_brain.semantics.recovery_guard import validate_recovery_scope
    decision = FailureContextDecision(decision="revise_task", source_turn_id="t1",
        resolved_instruction="删除苹果", amendments=[{
            "subject_role":"source", "field":"operation", "value":"delete", "evidence":{}}])
    with pytest.raises(ValueError, match="without_user_evidence: operation"):
        validate_recovery_scope(decision, root_instruction="把苹果放进篮子")


@pytest.mark.parametrize("subject,relation,accepted", [
    ("apple", "leftmost", True), ("basket", "leftmost", False),
    ("apple", "rightmost", False)])
def test_recovery_selection_checks_relation_and_subject(subject, relation, accepted):
    from types import SimpleNamespace as NS
    from robot_agent_brain.application import BrainApplication
    turn = NS(task_intent=NS(entities=[NS(entity_id="apple", semantic_name="apple"),
        NS(entity_id="basket",semantic_name="basket")],
        operations=[NS(source="apple",destination="basket")],
        spatial_relations=[NS(scope="selection",subject=subject,relation=relation)]))
    evidence={"accepted_amendments":[{"subject_role":"source", "field":"selection", "value":"leftmost"}]}
    if accepted:
        BrainApplication._validate_recovery_u_conditions(turn, evidence)
    else:
        with pytest.raises(ValueError, match="u_condition_lost:selection"):
            BrainApplication._validate_recovery_u_conditions(turn, evidence)


@pytest.mark.parametrize("source_mode,destination_mode,accepted", [
    ("all", "single", True), ("single", "all", False), ("single", "single", False)])
def test_recovery_all_selection_is_role_scoped(source_mode,destination_mode,accepted):
    from types import SimpleNamespace as NS
    from robot_agent_brain.application import BrainApplication
    turn=NS(task_intent=NS(entities=[NS(entity_id="a",semantic_name="apple",quantity_mode=source_mode),
        NS(entity_id="b",semantic_name="basket",quantity_mode=destination_mode)],
        operations=[NS(source="a",destination="b")],spatial_relations=[]))
    evidence={"accepted_amendments":[{"subject_role":"source","field":"selection","value":"all"}]}
    if accepted:
        BrainApplication._validate_recovery_u_conditions(turn,evidence)
    else:
        with pytest.raises(ValueError,match="u_condition_lost:selection"):
            BrainApplication._validate_recovery_u_conditions(turn,evidence)


@pytest.mark.parametrize("value,source_count,accepted", [
    (2,2,True),("2",2,True),("2",1,False),(True,1,False),
    ("2.5",2,False),("all",2,False),(0,0,False)])
def test_recovery_quantity_exact_integer_and_role(value,source_count,accepted):
    from types import SimpleNamespace as NS
    from robot_agent_brain.application import BrainApplication
    turn=NS(task_intent=NS(entities=[NS(entity_id="a",semantic_name="apple",count=source_count),
        NS(entity_id="b",semantic_name="basket",count=2)],
        operations=[NS(source="a",destination="b")],spatial_relations=[]))
    evidence={"accepted_amendments":[{"subject_role":"source","field":"quantity","value":value}]}
    if accepted:
        BrainApplication._validate_recovery_u_conditions(turn,evidence)
    else:
        with pytest.raises(ValueError,match="u_condition_lost:quantity"):
            BrainApplication._validate_recovery_u_conditions(turn,evidence)


@pytest.mark.parametrize("ids,value,accepted",[([17],17,True),([17],"17",True),
    ([17],"ID 17",True),([17],"id17",True),([8],"ID 17",False),
    ([17],"ID 17 or 8",False),([17],True,False),([8],17,False),([17,8],17,False)])
def test_recovery_explicit_id_is_preserved_uniquely(ids,value,accepted):
    from types import SimpleNamespace as NS
    from robot_agent_brain.application import BrainApplication
    turn=NS(task_intent=NS(entities=[NS(entity_id="a",semantic_name="apple",scene_object_ids=ids)],
        operations=[NS(source="a")],spatial_relations=[]))
    evidence={"accepted_amendments":[{"subject_role":"source","field":"selection","value":value}]}
    if accepted:
        BrainApplication._validate_recovery_u_conditions(turn,evidence)
    else:
        with pytest.raises(ValueError,match="u_condition_lost:selection"):
            BrainApplication._validate_recovery_u_conditions(turn,evidence)
