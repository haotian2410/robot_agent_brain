from types import SimpleNamespace

import pytest

from robot_agent_brain.scene.initial_robot import recover_initial_robot_name
from robot_agent_brain.session.conversation_memory import (
    ConversationMemory, ConversationTurn, FailureChain, StepLedgerEntry,
)


def fixture():
    text = '使用 er10 机械臂把苹果放到篮子里'
    turn = ConversationTurn(turn_id='t1', session_id='s', sequence=1,
        raw_user_text=text, final_outcome='failed', final_error_code='robot_asset_unknown',
        effect_evidence={'scene_effect': 'none_confirmed', 'execution_effect': 'not_started'})
    chain = FailureChain(chain_id='c1', root_failure_turn_id='t1', root_instruction=text,
        failed_user_turn_ids=['t1'], step_ledger=[StepLedgerEntry(
            step_id='step-1', original_step_index=1, instruction=text, status='rejected')])
    session = SimpleNamespace(scene=None, sync_state='synchronized', session_phase='setup',
        original_scene_manifest=None, platform_object_ids=set(), conversation_memory=ConversationMemory(
            recent_turns=[turn], active_failure_chain=chain))

    class Assembly:
        def resolve(self, name, *, role):
            assert role == 'arm'
            if name.casefold() != 'ur10':
                raise ValueError('robot_asset_unknown')
            return SimpleNamespace(semantic_name='ur10')

    return session, Assembly()


def test_model_correction_preserves_task_and_requires_normal_validation():
    session, assembly = fixture()
    before = session.conversation_memory.model_dump()
    result = recover_initial_robot_name(session, 'UR10', assembly)
    assert result['effective_instruction'] == '使用 ur10 把苹果放到篮子里'
    assert result['superseded_fields'] == {'initial_robot_asset': 'er10'}
    assert result['accepted_amendments'] == [{'field': 'initial_robot_asset', 'value': 'ur10'}]
    assert session.conversation_memory.model_dump() == before
    from robot_agent_brain.application import BrainApplication
    with pytest.raises(ValueError, match='failure_context_u_condition_lost:initial_robot_asset'):
        BrainApplication._validate_recovery_u_conditions(SimpleNamespace(initial_robot_asset='ur5'), result)
    BrainApplication._validate_recovery_u_conditions(SimpleNamespace(initial_robot_asset='ur10'), result)


def test_unknown_initial_model_feedback_preserves_diagnostic_code():
    from robot_agent_brain.errors import BrainIssue
    from robot_agent_brain.scene.user_feedback import explain_issue
    issue = BrainIssue(stage='bootstrap', code='robot_asset_unknown', message='robot_asset_unknown:er10')
    explain_issue(issue, ValueError(issue.message), None, None)
    assert issue.code == 'robot_asset_unknown'
    assert 'er10' in issue.clarification_question
    assert '上下文恢复' in issue.clarification_question
    assert '不会自动猜测' in issue.clarification_question
    assert issue.details['diagnostic_message'] == 'robot_asset_unknown:er10'


def test_web_recovery_uses_catalog_correction_without_recovery_model():
    from robot_agent_brain.web.service import AgentService
    session, assembly = fixture()
    service = object.__new__(AgentService)
    service.config = SimpleNamespace(conversation_recovery_enabled=True,
                                     conversation_recovery_max_failed_user_turns=5)
    # No provider or pipeline: this path must not depend on model repair.
    service.app = SimpleNamespace(robot_assembly=assembly)
    request = SimpleNamespace(command='ur10', sessionID='s', clientRequestID='t2')
    assert service._maybe_recover(session, request) == '使用 ur10 把苹果放到篮子里'
    assert session.last_recovery_evidence['raw_current_user_text'] == 'ur10'
    assert session.scene is None
    service.config.conversation_recovery_enabled = False
    assert service._maybe_recover(session, request) == 'ur10'


@pytest.mark.parametrize('command', ['er10', 'ur10并删除苹果', '使用ur10', '左边的'])
def test_only_exact_catalog_model_token_can_fill_slot(command):
    session, assembly = fixture()
    assert recover_initial_robot_name(session, command, assembly) is None


@pytest.mark.parametrize('change', ['initialized', 'unknown', 'effect', 'blocked', 'exhausted', 'wrong_error'])
def test_no_correction_after_initialization_or_uncertain_effects(change):
    session, assembly = fixture()
    chain = session.conversation_memory.active_failure_chain
    root = session.conversation_memory.recent_turns[0]
    if change == 'initialized':
        session.scene = SimpleNamespace(scene_id=1, objects=[object()])
    elif change == 'unknown':
        session.sync_state = 'uncertain'
    elif change == 'effect':
        root.effect_evidence.execution_effect = 'partial_confirmed'
    elif change == 'blocked':
        chain.state = 'blocked_system'
    elif change == 'exhausted':
        chain.failed_user_turn_ids = ['1', '2', '3', '4', '5']
    else:
        root.final_error_code = 'grounding_missing'
    assert recover_initial_robot_name(session, 'ur10', assembly) is None
