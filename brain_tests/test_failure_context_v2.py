import pytest

from robot_agent_brain.models.failure_context import (
    FailureContextDecision, FailureContextRequest,
)
from robot_agent_brain.session.conversation_memory import ConversationMemory, ConversationTurn, SelectionDecision
from robot_agent_brain.session.conversation_journal import ConversationJournal
from robot_agent_brain.semantics.recovery_guard import validate_recovery_decision, validate_recovery_scope


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
