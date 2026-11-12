"""S3: a sentence that asks for several things runs one subtask at a time.

The policy under test is 分一个做一个: every step lands its own side effect and
the walk stops at the first refusal, so an ambiguous third step never throws away
two finished ones -- and never quietly skips what came after it either.  The
provider is a double that answers the decomposition stage and then one turn per
step, which keeps the orchestration testable without Qwen or a simulator.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("aiohttp", reason="optional web integration dependencies not installed")
pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.decomposition import TaskDecomposition
from robot_agent_brain.contracts.task_intent import Operation, TaskEntity, TaskIntent
from robot_agent_brain.contracts.turn import BrainTurn, SceneQueryIntent
from robot_agent_brain.ports.execution import ExecutionOutcome, ExecutionStep
from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
from robot_agent_brain.web.service import AgentService
from test_scene_replace import plan
from test_web_gateway import Browser, adapter

LEFT = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="把苹果向左移动10厘米",
    scene_edit=plan([{"operation": "translate", "target": "old", "direction": "left", "distance_m": .1}]))
RIGHT = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="把苹果向右移动10厘米",
    scene_edit=plan([{"operation": "translate", "target": "old", "direction": "right", "distance_m": .1}]))
COUNT = BrainTurn(status="accepted", turn_kind="scene_query", instruction="数一数有几个苹果",
    scene_query=SceneQueryIntent(query_type="count", target="apple",
        entities=[dict(entity_id="apple", semantic_name="apple", category="fruit")]))
AMBIGUOUS = BrainTurn(status="clarification_required", turn_kind="scene_edit",
    instruction="把水果移到左边", clarification_question="请说明要移动哪个水果。")
HARD_ERROR = ValueError("provider_response_unavailable")
THREE = [("scene_edit", "把苹果向左移动10厘米"), ("scene_edit", "把苹果向右移动10厘米"),
         ("scene_query", "数一数有几个苹果")]
THREE_SENTENCE = "先把苹果向左移动10厘米，然后把苹果向右移动10厘米，最后数一数有几个苹果"
ARM_STEPS = [("scene_edit", "把苹果向左移动10厘米"), ("robot_task", "把苹果放到桌面上"),
             ("scene_edit", "把苹果向右移动10厘米")]
ARM_SENTENCE = "先把苹果向左移动10厘米，然后把苹果放到桌面上，再把苹果向右移动10厘米"
EXECUTABLE = dict(execution_python="/bin/false", execution_control_root="/tmp/control",
                  execution_library="/tmp/control/libsim_platform_c.so")


def place_on_table():
    """A robot turn whose every entity exists in the test world, so planning can succeed."""
    return BrainTurn(status="accepted", turn_kind="robot_task", instruction="把苹果放到桌面上",
        task_intent=TaskIntent(instruction="把苹果放到桌面上", entities=[
            TaskEntity(entity_id="a", semantic_name="apple", category="fruit", count=1, quantity_mode="all"),
            TaskEntity(entity_id="t", semantic_name="table", category="surface")],
            operations=[Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="t",
                                  placement_target={"kind": "support_surface", "reference": "t"})]))


class Split:
    """A provider with the decomposition stage: one split, then one turn per subtask."""

    def __init__(self, steps, answers):
        self.split = TaskDecomposition.model_validate({"steps": [
            {"kind": kind, "instruction": instruction} for kind, instruction in steps]})
        self.answers, self.asked, self.splits = list(answers), [], 0

    def decompose(self, request):
        self.splits += 1
        return self.split

    def understand_turn(self, request):
        self.asked.append(request.instruction)
        value = self.answers[len(self.asked) - 1]
        if isinstance(value, Exception):
            raise value
        return value


class Runner:
    """The execution port, answered from a recorded control report.

    ``moved`` is not decoration: a run that reports no executed pose writes no world
    back, which is what the two stop tests below pin down.  The default re-stamps the
    first command's own target just ahead of where the document puts it, which is the
    smallest honest report a real grasp-and-place round would file.
    """

    def __init__(self, *, ok=True, moved="target", holding=None, error="collision", succeed_after=None,
                 detail=None):
        self.ok, self.moved, self.holding, self.calls = ok, moved, holding, []
        self.error, self.succeed_after, self.detail = error, succeed_after, detail

    def run(self, commands, scene_document, *, progress=None):
        self.calls.append(commands)
        ok = self.ok if self.succeed_after is None else len(self.calls) > self.succeed_after
        moved = {}
        if self.moved == "target":
            for operation in scene_document.get("objects", []):
                if operation["object_id_in_scene"] == self.moved_target(commands):
                    position = next(component for component in operation["components"]
                                    if component["component_type"] == "Transform")["properties"]["position"]
                    moved[self.moved_target(commands)] = {
                        "position": [position[0] + .01, position[1], position[2]],
                        "quaternion_xyzw": [0, 0, 0, 1]}
        elif self.moved:
            moved = self.moved
        return ExecutionOutcome(ok=ok, moved=moved, holding_object=self.holding,
            traj_path="/tmp/composite.traj" if ok else None,
            error_code=None if ok else self.error, detail=self.detail,
            steps=[ExecutionStep(command_id=step.command_id, skill_name=step.skill_name,
                                 status="success" if ok else "failed",
                                 error_code=None if ok else self.error)
                   for step in commands.commands])

    @staticmethod
    def moved_target(commands):
        target = commands.commands[0].parameters.target
        return target if isinstance(target, int) else None


def walk(tmp_path, steps, answers, command, *, runner=None, **config):
    """Run one WebEditor task over the doubles and hand back what the panel would read."""
    browser, provider = Browser(), Split(steps, answers)
    service = AgentService(BrainConfig(provider="replay", planner="recipe", scene_id_bits=32,
        scene_platform_object_ids={0}, output_dir=str(tmp_path), debug=True, **config),
        provider=provider,
        platform_factory=lambda binding: adapter(browser, tmp_path / binding["id"] / "gateway_transactions"))
    session_id = service.activate(SessionRequest(browserID="b"))["sessionID"]
    if runner is not None:
        service.execution_port = runner
    record, fresh = service.tasks.submit(StartTask(command=command, scene=browser.scene, sessionID=session_id,
                                                   clientRequestID="composite", browserID="b",
                                                   sceneDigest=digest(browser.scene)))
    trajs = service.execute(record["id"])
    return SimpleNamespace(service=service, browser=browser, provider=provider, session_id=session_id,
                           session=service.app.get_session(session_id), trajs=trajs,
                           binding=service.tasks.binding(session_id),
                           record=service.tasks.get(record["id"]),
                           result=service.tasks.get(record["id"])["result"])


def steps_of(result):
    return result["metrics"]["steps"]


def states(result):
    return [step["state"] for step in steps_of(result)]


def commits(browser):
    return browser.calls.count(("POST", "/commitWorld"))


def test_each_step_lands_and_the_sentence_reports_the_sum(tmp_path):
    walked = walk(tmp_path, THREE, [LEFT, RIGHT, COUNT], THREE_SENTENCE)
    result = walked.result
    assert [step["outcome"] for step in steps_of(result)] == ["scene_updated", "scene_updated", "answered"]
    assert states(result) == ["completed"] * 3
    assert result["outcome"] == "scene_updated" and result["executed"] is False
    assert commits(walked.browser) == 2 and len(result["commitReceipts"]) == 2
    assert walked.browser.scene.scene_version == 2
    assert result["metrics"]["subtasks"] == 3
    # The world moved twice, so the reply enumerates the work instead of claiming one edit.
    assert "已完成 3 步" in result["reply"] and "①" in result["reply"] and "③" in result["reply"]
    assert walked.provider.asked == [step for _, step in THREE]


def test_the_split_is_asked_once_and_in_utterance_order(tmp_path):
    walked = walk(tmp_path, THREE, [LEFT, RIGHT, COUNT], THREE_SENTENCE)
    assert walked.provider.splits == 1
    assert walked.result["metrics"]["steps"][0]["kind"] == "scene_edit"


def test_an_ambiguous_third_step_keeps_the_two_landings_and_parks_the_fourth(tmp_path):
    steps = THREE[:2] + [("scene_edit", "把水果移到左边"), ("scene_query", "数一数有几个苹果")]
    walked = walk(tmp_path, steps, [LEFT, RIGHT, AMBIGUOUS, COUNT],
                  "先把苹果向左移动10厘米，然后把苹果向右移动10厘米，再把水果移到左边，最后数一数有几个苹果")
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed", "completed", "stopped", "not_run"]
    assert records[2]["outcome"] == "clarification_required"
    # Steps 1 and 2 are real: two commits landed, and nothing after the refusal was written.
    assert commits(walked.browser) == 2
    assert "请说明要移动哪个水果" in result["reply"] and "第 3 步" in result["reply"]
    assert "后续 1 步未执行" in result["reply"]
    assert result["outcome"] == "clarification_required"
    assert result["clarification_question"] == "请说明要移动哪个水果。"
    # A semantic stop is a clean stop: the lease goes back to the editor, unlocked.
    assert walked.record["state"] == "等待澄清" and not walked.binding["uncertain"]
    assert walked.session.session_phase == "setup"


def test_a_hard_failure_stops_the_walk_after_the_first_landing(tmp_path):
    walked = walk(tmp_path, THREE, [LEFT, HARD_ERROR, COUNT], THREE_SENTENCE)
    result = walked.result
    assert states(result) == ["completed", "stopped", "not_run"]
    assert result["outcome"] == "failed" and walked.record["state"] == "任务失败"
    assert result["error"]["code"] == "provider_response_unavailable"
    assert commits(walked.browser) == 1
    assert "第 2 步" in result["reply"] and "后续 1 步未执行" in result["reply"]
    # The failing step never reached the gateway, so nothing about the world is unknown.
    assert not walked.binding["uncertain"]


def test_a_plan_nobody_ran_parks_the_rest_of_the_sentence(tmp_path):
    """With execution off the robot step only exports, and an export claims the scene version.

    Committing a later step would invalidate the very plan the user was shown, so
    the walk stops on the unexecuted plan instead of producing a dead document.
    """
    walked = walk(tmp_path, ARM_STEPS, [LEFT, place_on_table(), RIGHT], ARM_SENTENCE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed", "stopped", "not_run"]
    assert records[1]["stop_reason"] == "plan_not_executed"
    assert result["outcome"] == "plan_ready" and "只生成了计划" in result["reply"]
    assert commits(walked.browser) == 1 and "commands" in result["_artifact_paths"]


def test_a_successful_run_leaves_the_next_step_free_to_write(tmp_path):
    runner = Runner()
    walked = walk(tmp_path, ARM_STEPS, [LEFT, place_on_table(), RIGHT], ARM_SENTENCE,
                  runner=runner, execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert records[1]["outcome"] == "scene_updated" and records[1]["executed"] is True
    assert runner.calls and states(result) == ["completed"] * 3
    # The two edits committed, and the run committed its executed pose as a third world.
    assert commits(walked.browser) == 3 and walked.trajs == ["/tmp/composite.traj"]
    assert "②把苹果放到桌面上（已执行并写回场景）" in result["reply"]
    # Step 3 is planned against what step 2 left behind, not against the first document.
    assert walked.service.app.get_session(walked.session_id).scene.scene_version == 3


def test_three_arm_runs_in_one_sentence_chain_the_executed_world(tmp_path):
    """The 放进篮子 / 拿出来 / 再放篮子 shape: one physical run per arm clause, in order.

    Every run has to hand its executed pose to the next step, because the control side
    rebuilds its simulator from the browser document -- so the world the third grasp
    sees is the world the second run left, not the one the user first opened.
    """
    steps = [("robot_task", "把苹果放到篮子里"), ("robot_task", "把苹果拿出来放到桌面上"),
             ("scene_edit", "把苹果向右移动10厘米"), ("robot_task", "把香蕉放到篮子里"),
             ("scene_edit", "把苹果向左移动10厘米")]
    sentence = "把苹果放到篮子里，再把苹果拿出来放到桌面上，然后把苹果向右移动10厘米，" \
               "把香蕉放到篮子里，最后把苹果向左移动10厘米"
    runner = Runner()
    walked = walk(tmp_path, steps, [place_on_table(), place_on_table(), RIGHT, place_on_table(), LEFT],
                  sentence, runner=runner, execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed"] * 5
    # One run per arm clause, and the two scene edits committed alongside them.
    assert len(runner.calls) == 3 and commits(walked.browser) == 5
    assert len(walked.trajs) == 3
    assert result["outcome"] == "scene_updated" and result["executed"] is True
    assert "已完成 5 步" in result["reply"] and "⑤" in result["reply"]
    # Each run is planned against the version its predecessor left behind, so the three
    # command documents never share a base scene version.
    assert len({commands.scene_version for commands in runner.calls}) == 3


def test_a_run_that_reports_no_pose_stops_the_chain_before_the_next_grasp(tmp_path):
    """Nothing written back means the browser still shows the pre-run world.

    The following arm run rebuilds its simulator from that document, so chaining would
    have it grasp an object the previous run supposedly already moved -- and the reply
    would still say 已执行并写回场景.
    """
    walked = walk(tmp_path, ARM_STEPS, [LEFT, place_on_table(), RIGHT], ARM_SENTENCE,
                  runner=Runner(moved=None), execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed", "stopped", "not_run"]
    assert records[1]["stop_reason"] == "execution_writeback_missing"
    # The run really happened, so the honest verdict names the missing evidence.
    assert records[1]["verdict"] == "已执行未报告位姿"
    assert "没有报告任何物体的新位姿" in result["reply"] and "后续 1 步未执行" in result["reply"]
    assert commits(walked.browser) == 1


def test_a_run_that_ends_holding_stops_the_chain(tmp_path):
    """The rebuild starts with empty fingers, so a held object cannot carry over."""
    walked = walk(tmp_path, ARM_STEPS, [LEFT, place_on_table(), RIGHT], ARM_SENTENCE,
                  runner=Runner(holding=1), execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed", "stopped", "not_run"]
    assert records[1]["stop_reason"] == "arm_still_holding"
    assert "夹爪仍持有物体" in result["reply"]
    assert walked.trajs == ["/tmp/composite.traj"]


def test_a_run_that_failed_stops_the_walk_and_writes_nothing_back(tmp_path):
    runner = Runner(ok=False)
    walked = walk(tmp_path, ARM_STEPS, [LEFT, place_on_table(), RIGHT], ARM_SENTENCE,
                  runner=runner, execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed", "stopped", "not_run"]
    assert result["outcome"] == "failed" and commits(walked.browser) == 1
    # A collision refusal is a decision about the plan, not a coin flip, so it is not repeated.
    assert len(runner.calls) == 1 and records[1]["attempts"] == 1
    # A run that came back confirmed is a known world, not a quarantined one.
    assert not walked.binding["uncertain"] and walked.session.sync_state == "synchronized"


@pytest.mark.parametrize("code", ["GRASP_NOT_CONFIRMED", "GRASP_FAILED", "PLACEMENT_HEIGHT_SEARCH_FAILED",
                                  "PATH_CONSTRAINT_INFEASIBLE"])
def test_an_empty_grip_is_tried_again_and_the_reply_says_which_try_landed(code, tmp_path):
    """The RGB-D grasp and drop points jitter by about a centimetre between attempts.

    A grip that closed on nothing, a grip that lost the object while travelling, a
    drop the height search refused, and a retreat the planner refused because *this*
    attempt's physics left the carried object 0.324 mm inside the container wall all
    report the same thing: the skill never landed, so nothing was written back.  Each
    therefore gets another sample, and naming the attempt in the reply is what keeps
    the retry observable.
    """
    runner = Runner(error=code, succeed_after=1)
    walked = walk(tmp_path, ARM_STEPS, [LEFT, place_on_table(), place_on_table(), RIGHT], ARM_SENTENCE,
                  runner=runner, execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed"] * 3 and len(runner.calls) == 2
    assert records[1]["attempts"] == 2 and result["outcome"] == "scene_updated"
    assert "②把苹果放到桌面上（已执行并写回场景、第 2 次尝试）" in result["reply"]
    # The empty grip committed nothing, so the three commits belong to the three steps.
    assert commits(walked.browser) == 3 and walked.trajs == ["/tmp/composite.traj"]


def test_a_grasp_that_never_contacts_stops_after_the_attempts_are_spent(tmp_path):
    evidence = "16 档抓深均不可行：目标位姿间距不足或碰撞 64 次"
    runner = Runner(error="GRASP_NOT_CONFIRMED", detail=evidence, succeed_after=99)
    walked = walk(tmp_path, ARM_STEPS, [LEFT] + [place_on_table()] * AgentService.MAX_STEP_ATTEMPTS + [RIGHT],
                  ARM_SENTENCE, runner=runner, execution_enabled=True, **EXECUTABLE)
    result, records = walked.result, steps_of(walked.result)
    assert states(result) == ["completed", "stopped", "not_run"]
    assert len(runner.calls) == AgentService.MAX_STEP_ATTEMPTS
    assert records[1]["attempts"] == AgentService.MAX_STEP_ATTEMPTS
    assert result["outcome"] == "failed" and commits(walked.browser) == 1
    retries = AgentService.MAX_STEP_ATTEMPTS - 1
    assert f"重试 {retries} 次后仍未成功" in result["reply"] and "后续 1 步未执行" in result["reply"]
    # The stopped step quotes what the control measured, not just its enum: a reader of
    # the panel learns which search ran out, while the code stays for the diagnostics.
    assert f"未完成：{evidence}（GRASP_NOT_CONFIRMED）" in result["reply"]


def test_an_evidence_sentence_that_already_names_its_code_is_not_repeated(tmp_path):
    """error_messages renders 「中文句（CODE）」, so the reply must not add a second copy."""
    evidence = "command 结束后，持物未保持双侧指垫接触（GRASP_FAILED）"
    runner = Runner(error="GRASP_FAILED", detail=evidence, succeed_after=99)
    walked = walk(tmp_path, ARM_STEPS, [LEFT] + [place_on_table()] * AgentService.MAX_STEP_ATTEMPTS + [RIGHT],
                  ARM_SENTENCE, runner=runner, execution_enabled=True, **EXECUTABLE)
    result = walked.result
    assert result["outcome"] == "failed"
    assert f"未完成：{evidence}，" in result["reply"]
    assert result["reply"].count("GRASP_FAILED") == 1


def test_a_platform_rebind_never_takes_the_composite_path(tmp_path):
    browser = Browser()
    provider = Split(THREE, [LEFT, RIGHT, COUNT])
    service = AgentService(BrainConfig(provider="replay", planner="recipe", scene_id_bits=32,
        scene_platform_object_ids={0}, output_dir=str(tmp_path), debug=True), provider=provider,
        platform_factory=lambda binding: adapter(browser, tmp_path / binding["id"] / "gateway_transactions"))
    session_id = service.activate(SessionRequest(browserID="b"))["sessionID"]
    assert service.decomposition(SimpleNamespace(change_kind="platform_rebind", command=THREE_SENTENCE),
                                 service.app.get_session(session_id)) is None
    assert provider.splits == 0


def test_without_the_stage_the_multi_clause_sentence_still_fails_as_before(tmp_path):
    """The fallback is a no-op, not a repair: this is the pre-S3 verdict verbatim."""
    from test_application_artifacts import Provider
    browser = Browser()
    service = AgentService(BrainConfig(provider="replay", planner="recipe", scene_id_bits=32,
        scene_platform_object_ids={0}, output_dir=str(tmp_path), debug=True), provider=Provider(LEFT),
        platform_factory=lambda binding: adapter(browser, tmp_path / binding["id"] / "gateway_transactions"))
    session_id = service.activate(SessionRequest(browserID="b"))["sessionID"]
    record, _ = service.tasks.submit(StartTask(command=THREE_SENTENCE, scene=browser.scene,
        sessionID=session_id, clientRequestID="single", browserID="b", sceneDigest=digest(browser.scene)))
    service.execute(record["id"])
    result = service.tasks.get(record["id"])["result"]
    assert "steps" not in result["metrics"] and "subtasks" not in result["metrics"]
    assert result["outcome"] == "failed" and result["error"]["code"] == "motion_clause_binding_ambiguous"
    assert commits(browser) == 0
