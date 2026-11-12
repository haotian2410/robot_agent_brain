"""The decomposition stage: what it may say, and what it may never decide.

Splitting an utterance is an optimisation over the existing single-turn path,
so every test here asks the same question in a different shape: does this
output describe work the user actually asked for, in the order they asked --
and if not, do we fall back rather than improvise?
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from robot_agent_brain.contracts.decomposition import MAX_SUBTASKS, Subtask, SubtaskKind, TaskDecomposition
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.task_decomposition import (TaskDecompositionRequest, parse_decomposition,
                                                        task_decomposition_wire_schema, worth_splitting)
from robot_agent_brain.pipeline import BrainPipeline

EDIT = {"kind": "scene_edit", "instruction": "在桌子左边增加一个苹果"}
ARM = {"kind": "robot_task", "instruction": "把苹果放进篮子"}
QUERY = {"kind": "scene_query", "instruction": "篮子里有什么"}


def answer(*steps):
    return httpx.Response(200, json={"choices": [
        {"message": {"content": json.dumps({"steps": list(steps)}, ensure_ascii=False)},
         "finish_reason": "stop"}]})


def provider(*answers):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return answers.pop(0) if answers else answer([EDIT])
    answers = list(answers)
    return QwenHTTPProvider("http://example/v1", "qwen-test",
                            transport=httpx.MockTransport(handler)), requests


class TestContract:
    def test_a_sequence_of_four_is_the_longest_the_caller_will_walk(self):
        value = TaskDecomposition.model_validate({"steps": [
            {"kind": "scene_query", "instruction": f"第{i}件事"} for i in range(MAX_SUBTASKS)]})
        assert value.composite

    def test_a_step_beyond_the_ceiling_is_not_a_split_but_a_new_task(self):
        with pytest.raises(ValidationError):
            TaskDecomposition.model_validate({"steps": [
                {"kind": "scene_query", "instruction": f"第{i}件事"} for i in range(MAX_SUBTASKS + 1)]})

    def test_several_arm_tasks_are_one_utterance(self):
        """The user's 「放进篮子，再拿出来放桌子左边」 is two runs, and both are asked for.

        Each dispatch commits its executed poses before the next step is understood, so
        the second run rebuilds the world the first one left -- the intermediate state is
        the user's own sequence, not an invention of this stage.
        """
        value = TaskDecomposition.model_validate({"steps": [ARM, {**ARM, "instruction": "把香蕉放到左边"}]})
        assert [step.kind for step in value.steps] == [SubtaskKind.ROBOT_TASK, SubtaskKind.ROBOT_TASK]

    def test_the_five_clause_sentence_splits_into_five_legal_steps(self):
        value = TaskDecomposition.model_validate({"steps": [
            {"kind": "robot_task", "instruction": "把苹果放到篮子里"},
            {"kind": "robot_task", "instruction": "把苹果拿出来放到桌子左边"},
            {"kind": "scene_edit", "instruction": "新增一个香蕉"},
            {"kind": "robot_task", "instruction": "把香蕉放到篮子里"},
            {"kind": "scene_edit", "instruction": "把所有香蕉改成绿色"}]})
        assert [step.kind.value for step in value.steps] == [
            "robot_task", "robot_task", "scene_edit", "robot_task", "scene_edit"]

    def test_pasting_the_whole_sentence_into_every_step_is_not_a_split(self):
        with pytest.raises(ValidationError, match="decomposition_steps_repeated"):
            TaskDecomposition.model_validate({"steps": [EDIT, dict(EDIT)]})

    @pytest.mark.parametrize("step", [{"kind": "session_control", "instruction": "换一个机器人"},
                                      {"kind": "scene_edit", "instruction": "   "}])
    def test_a_step_that_is_not_an_ordinary_task_is_rejected(self, step):
        with pytest.raises(ValidationError):
            Subtask.model_validate(step)

    def test_surrounding_whitespace_is_the_only_rewrite_this_stage_makes(self):
        value = TaskDecomposition.model_validate({"steps": [EDIT, {**ARM, "instruction": "  把苹果放进篮子  "}]})
        assert value.steps[1].instruction == "把苹果放进篮子"


class TestWire:
    def test_the_schema_offers_exactly_the_kinds_the_contract_accepts(self):
        kinds = task_decomposition_wire_schema()["properties"]["steps"]["items"]["properties"]["kind"]
        assert kinds["enum"] == ["scene_edit", "robot_task", "scene_query"]

    def test_an_array_answer_is_the_same_document_without_the_envelope(self):
        assert [step.instruction for step in parse_decomposition([EDIT, ARM]).steps] == [
            "在桌子左边增加一个苹果", "把苹果放进篮子"]

    def test_a_step_carrying_semantic_fields_is_refused_not_interpreted(self):
        # Those fields belong to the understanding round; accepting them here
        # would make this stage a second, weaker route classifier.
        with pytest.raises(ValidationError):
            parse_decomposition({"steps": [{**EDIT, "entities": []}]})


class TestSequencingGate:
    def test_compact_and_clause_is_a_composite_task(self):
        assert worth_splitting("把最左边的苹果改成绿色并把他放到托盘里")

    def test_plain_and_expression_is_not_alone_a_composite_marker(self):
        assert not worth_splitting("场景中并不存在蓝色苹果")

    def test_compact_and_split_keeps_the_pronoun_for_dialogue_binding(self):
        value = parse_decomposition({"steps": [
            {"kind": "scene_edit", "instruction": "把最左边的苹果改成绿色"},
            {"kind": "robot_task", "instruction": "把他放到托盘里"},
        ]})
        assert value.steps[1].instruction == "把他放到托盘里"

    @pytest.mark.parametrize("instruction", [
        "先增加一个苹果，然后把苹果放进篮子",
        "把苹果放进篮子，再把篮子设为蓝色",
        "数一下有几个苹果。然后把苹果放进篮子。",
        "Add an apple, then put it in the basket",
    ])
    def test_a_sentence_with_order_in_it_gets_the_second_round(self, instruction):
        assert worth_splitting(instruction)

    @pytest.mark.parametrize("instruction", [
        "把苹果放进篮子",
        "在桌子左边增加一个苹果",
        "把红色的苹果放进蓝色的篮子里",
        "篮子里有什么",
    ])
    def test_one_task_does_not_pay_for_a_second_round(self, instruction):
        assert not worth_splitting(instruction)


class TestProvider:
    def test_the_split_comes_back_as_the_ordered_steps_it_was_asked_for(self):
        client, requests = provider(answer(EDIT, ARM))
        value = client.decompose(TaskDecompositionRequest(instruction="先增加苹果然后把苹果放进篮子"))
        assert [step.kind.value for step in value.steps] == ["scene_edit", "robot_task"]
        assert requests[0]["response_format"]["json_schema"]["name"] == "task_decomposition"
        assert "steps" in requests[0]["response_format"]["json_schema"]["schema"]["properties"]

    def test_an_illegal_split_gets_one_repair_turn_that_quotes_the_violation(self):
        client, requests = provider(answer({**ARM, "kind": "session_control"}), answer(EDIT, ARM))
        value = client.decompose(TaskDecompositionRequest(instruction="先增加苹果然后把苹果放进篮子"))
        assert len(requests) == 2 and value.composite
        assert "上一轮输出不被接受" in requests[1]["messages"][0]["content"]

    def test_a_second_illegal_answer_is_the_last_one(self):
        client, requests = provider(answer({**ARM, "kind": "session_control"}),
                                    answer({"steps": [dict(ARM, instruction="不合法"), dict(ARM)]}))
        with pytest.raises(QwenProviderError):
            client.decompose(TaskDecompositionRequest(instruction="先增加苹果然后把苹果放进篮子"))
        assert len(requests) == 2


class Stub:
    def __init__(self, value=None, error=None):
        self.value, self.error, self.calls = value, error, []

    def decompose(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.value


class TestPipeline:
    def test_a_provider_without_the_stage_is_not_a_failure(self):
        assert BrainPipeline(object(), object()).decompose("先加苹果再放进篮子") is None

    def test_one_step_is_the_single_turn_path_under_another_name(self):
        stub = Stub(TaskDecomposition.model_validate({"steps": [ARM]}))
        assert BrainPipeline(stub, object()).decompose(
            "先看一下现场，然后把苹果放进篮子") is None
        assert len(stub.calls) == 1      # asked, and the model itself declined to split

    @pytest.mark.parametrize("error", [QwenProviderError("down"), ValueError("scene_object_rejected:x"),
                                       OSError("transport")])
    def test_any_refusal_from_this_stage_falls_back_rather_than_failing_the_turn(self, error):
        assert BrainPipeline(Stub(error=error), object()).decompose(
            "先增加苹果，然后把苹果放进篮子") is None

    def test_a_split_the_caller_can_walk_reaches_the_orchestrator(self):
        stub = Stub(TaskDecomposition.model_validate({"steps": [EDIT, ARM]}))
        value = BrainPipeline(stub, object()).decompose("先增加苹果，然后把苹果放进篮子", scene=None)
        assert [step.kind.value for step in value.steps] == ["scene_edit", "robot_task"]
        assert stub.calls[0].instruction == "先增加苹果，然后把苹果放进篮子"

    def test_pipeline_restores_a_user_pronoun_if_decomposer_rewrites_it(self):
        stub = Stub(TaskDecomposition.model_validate({"steps": [
            {"kind": "scene_edit", "instruction": "把最左边的苹果改成绿色"},
            # Simulate the provider's unsafe rewrite of “他” to a name.
            {"kind": "robot_task", "instruction": "把苹果放到托盘里"},
        ]}))
        value = BrainPipeline(stub, object()).decompose(
            "把最左边的苹果改成绿色并把他放到托盘里")
        assert value.steps[1].instruction == "把他放到托盘里"

    def test_an_utterance_with_no_order_in_it_never_pays_for_the_stage(self):
        stub = Stub(TaskDecomposition.model_validate({"steps": [EDIT]}))
        assert BrainPipeline(stub, object()).decompose("把苹果放进篮子") is None
        assert stub.calls == []
