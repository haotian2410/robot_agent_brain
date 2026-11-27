from types import SimpleNamespace

from robot_agent_brain.contracts.task_intent import TaskEntity, TaskIntent, Operation, TaskType
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.grounding.scene_reference_resolver import SceneReferenceResolver
from robot_agent_brain.session.conversation_memory import (
    ConversationMemory, ConversationTurn, FailureChainState,
)
from robot_agent_brain.web.service import AgentService
from test_query_scene_continuity import supported_scene


def test_scene_reference_uses_ols_style_canonical_names():
    scene = supported_scene()
    scene.objects[1].object_name_in_scene = "ToyPanda"
    semantic = next(c for c in scene.objects[1].components if c.component_type == "Semantic")
    semantic.properties["semantic_name"] = "ToyPanda"
    resolved = SceneReferenceResolver().resolve("熊猫", entities=[], scene=scene)
    assert resolved.object_id == 1
    assert resolved.canonical_id == "toy_panda"


def test_complete_new_task_supersedes_failure_chain_before_recovery():
    memory = ConversationMemory()
    memory.begin_failure(ConversationTurn(
        turn_id="web-old", session_id="s", sequence=1,
        raw_user_text="把熊猫移动到苹果右边", final_outcome="clarification_required"))

    intent = TaskIntent(
        instruction="拉开抽屉",
        entities=[TaskEntity(entity_id="drawer", semantic_name="drawer", category="container"),
                  TaskEntity(entity_id="handle", semantic_name="handle", category="object")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.OPEN, target="drawer", reference="handle")],
    )
    class Provider:
        def recover_failure(self, _payload):
            raise AssertionError("complete command must not enter failure recovery")

    service = object.__new__(AgentService)
    service.config = SimpleNamespace(
        conversation_recovery_enabled=True,
        conversation_recovery_max_failed_user_turns=5,
        conversation_recovery_max_input_chars=48000,
    )
    service.app = SimpleNamespace(
        provider=Provider(),
        pipeline=SimpleNamespace(understand_turn=lambda instruction, **_: BrainTurn(
            status="accepted", turn_kind="robot_task", instruction=instruction, task_intent=intent)),
    )
    session = SimpleNamespace(conversation_memory=memory, scene=None, dialogue=SimpleNamespace(),
                              last_recovery_evidence=None, original_understanding_context=lambda: None)
    request = SimpleNamespace(sessionID="s", clientRequestID="new", command="拉开抽屉", new_task=False)

    assert service._maybe_recover(session, request) == "拉开抽屉"
    assert memory.active_failure_chain.state == FailureChainState.SUPERSEDED
    assert memory.active_failure_chain.latest_question is None


def test_complete_new_task_can_escape_blocked_failure_chain():
    memory = ConversationMemory()
    memory.begin_failure(ConversationTurn(
        turn_id="web-old", session_id="s", sequence=1,
        raw_user_text="拉开抽屉", final_outcome="clarification_required"))
    memory.active_failure_chain.state = FailureChainState.BLOCKED_SYSTEM

    intent = TaskIntent(
        instruction="拉开抽屉",
        entities=[TaskEntity(entity_id="drawer", semantic_name="drawer", category="object")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.OPEN,
                              target="drawer", reference=None)],
    )

    class Provider:
        def recover_failure(self, _payload):
            raise AssertionError("a complete command must not enter blocked recovery")

    service = object.__new__(AgentService)
    service.config = SimpleNamespace(
        conversation_recovery_enabled=True,
        conversation_recovery_max_failed_user_turns=5,
        conversation_recovery_max_input_chars=48000,
    )
    service.app = SimpleNamespace(
        provider=Provider(),
        pipeline=SimpleNamespace(understand_turn=lambda instruction, **_: BrainTurn(
            status="accepted", turn_kind="robot_task", instruction=instruction,
            task_intent=intent)),
    )
    session = SimpleNamespace(conversation_memory=memory, scene=None,
                              dialogue=SimpleNamespace(), last_recovery_evidence=None,
                              original_understanding_context=lambda: None)
    request = SimpleNamespace(sessionID="s", clientRequestID="new", command="重新拉开抽屉",
                              new_task=False)

    assert service._maybe_recover(session, request) == "重新拉开抽屉"
    assert memory.active_failure_chain.state == FailureChainState.SUPERSEDED
