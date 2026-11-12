"""Round one plus the control atomic round, through the real application and wire artifacts."""
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.commands import parse_commands
from robot_agent_brain.contracts.commands_atomic import AtomicCommandsFile
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.planning.atomic_plan_validator import PLACEMENT_EDGE_OFFSET_M
from test_application_artifacts import Provider, robot
from test_qwen_http import response, PAUSE


UNDERSTANDING = {
    "status": "accepted", "turn_kind": "robot_task",
    "entities": [{"id": "a", "name": "apple", "category": "fruit"},
                 {"id": "b", "name": "basket", "category": "container"}],
    "operations": [{"type": "pick_and_place", "source": "a", "destination": "b",
                    "placement_target": {"kind": "container_interior", "reference": "b", "relation": "inside"}}],
}


def transfer(source, destination, **put_parameters):
    return [{"command_id": "1", "skill_name": "approach", "parameters": {"target": source}},
            {"command_id": "2", "skill_name": "pick", "parameters": {"target": source}},
            {"command_id": "3", "skill_name": "lift_up", "parameters": {}},
            {"command_id": "4", "skill_name": "retreat", "parameters": {"target": source}},
            {"command_id": "5", "skill_name": "approach", "parameters": {"target": destination}},
            {"command_id": "6", "skill_name": "put", "parameters": {"target": destination, **put_parameters}},
            {"command_id": "7", "skill_name": "retreat", "parameters": {"target": destination}}]


def payload_content(request_payload):
    """The user message the planning round was actually given."""
    return json.loads(request_payload["messages"][1]["content"])


def answer_for(content):
    """The control graph addressed with the scene IDs this very context advertises."""
    binding = content["operations"][0]["role_object_ids"]
    return {"commands": transfer(binding["source"], binding["destination"])}


def app_with_responses(tmp_path, bodies, *, mode="qwen", debug=True, **config_kwargs):
    pending = iter(bodies)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        body = next(pending)
        if callable(body):
            body = body(payload_content(payload))
        return httpx.Response(200, json=response(raw=json.dumps(body)))
    provider = QwenHTTPProvider("http://example/v1", "test-model", transport=httpx.MockTransport(handler))
    app = BrainApplication(BrainConfig(model="test-model", planner=mode, output_dir=str(tmp_path), debug=debug,
                                      **config_kwargs), provider=provider)
    return app, provider, requests


def wire(report):
    return json.loads(Path(report.artifacts["commands"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode,count,used", [("recipe", 1, "recipe"), ("auto", 1, "recipe"), ("qwen", 2, "qwen")])
def test_http_two_stage_integration_and_commands_schema(tmp_path, mode, count, used):
    app, provider, requests = app_with_responses(tmp_path, [UNDERSTANDING, answer_for], mode=mode)
    report = app.handle("把苹果放进篮子", session_id="e2e")
    assert report.run_status == "success", report.error
    assert report.executed is False
    assert report.metrics["understanding_calls"] == 1
    assert report.metrics["skill_planning_calls"] == count - 1
    assert report.metrics["planner_used"] == used and report.metrics["planner_requested"] == mode
    assert len(provider.calls) == len(requests) == count
    payload = wire(report)
    Draft202012Validator(AtomicCommandsFile.model_json_schema()).validate(payload)
    assert isinstance(parse_commands(payload), AtomicCommandsFile)
    assert (payload["scene_id"], payload["scene_version"]) == (report.scene_id, report.scene_version)
    assert [item["skill_name"] for item in payload["commands"]] == [
        "approach", "pick", "lift_up", "retreat", "approach", "put", "retreat"]
    assert [item["command_id"] for item in payload["commands"]] == [str(i) for i in range(1, 8)]
    # skill.md's assembly graph dropped its home transit in control commit 414195b.
    assert "home" not in {str(item["parameters"].get("target")) for item in payload["commands"]}
    assert "target" not in payload["commands"][2]["parameters"]
    assert payload["commands"][5]["parameters"] == {"target": payload["commands"][4]["parameters"]["target"]}
    if mode == "qwen":
        folder = Path(report.artifacts["debug"])
        for file in ("planner_context.json", "raw_skill_plan.json", "normalized_skill_plan.json",
                     "skill_plan_validation.json"):
            assert (folder / file).is_file()
        assert not (folder / "planner_skill_catalog.txt").exists()
        assert json.loads((folder / "raw_skill_plan.json").read_text(encoding="utf-8")) == answer_for(payload_content(requests[1]))
        assert json.loads((folder / "skill_plan_validation.json").read_text(
            encoding="utf-8"))["scope"] == "atomic_assembly"
        assert [call["stage"] for call in report.metrics["model_calls"]] == ["task_understanding", "skill_planning"]
        assert json.loads((folder / "planner_context.json").read_text(encoding="utf-8"))["entities"][0][
            "scene_object_id"] > 0
    else:
        assert "move_to" not in [item["skill_name"] for item in payload["commands"]]


def test_a_vertical_landing_hovers_instead_of_stopping(tmp_path):
    """「悬空放到篮子上面」 used to stop the plan; control commit ``b24cc3f`` added
    the world-Z relations, so the landing now reaches the wire as one ``put``.
    """
    understanding = {**UNDERSTANDING, "operations": [
        {"type": "pick_and_place", "source": "a", "destination": "b",
         "placement_target": {"kind": "relative_object", "reference": "b", "relation": "above"}}]}
    app, provider, requests = app_with_responses(tmp_path, [understanding, answer_for])
    report = app.handle("把苹果悬空放到篮子上面", session_id="above")
    assert report.run_status == "success", report.error
    assert len(provider.calls) == len(requests) == 2
    payload = wire(report)
    assert payload["commands"][5]["parameters"] == {
        "target": payload["commands"][4]["parameters"]["target"],
        "relation": "above", "distance_m": PLACEMENT_EDGE_OFFSET_M}


@pytest.mark.parametrize("emitted", [{}, {"relation": "right", "distance_m": 0.25}])
def test_a_side_landing_ships_the_side_the_task_asked_for(tmp_path, emitted):
    """「篮子前面」 used to stop the plan; the control offsets one side, so it now ships.

    The task owns both the side and the clearance: an omitted offset is filled in
    and a guessed one is overwritten, because the semantic contract carries no
    distance for an arm placement.
    """
    understanding = {**UNDERSTANDING, "operations": [
        {"type": "pick_and_place", "source": "a", "destination": "b",
         "placement_target": {"kind": "relative_object", "reference": "b", "relation": "front_of"}}]}

    def answer(content):
        binding = content["operations"][0]["role_object_ids"]
        return {"commands": transfer(binding["source"], binding["destination"], **emitted)}

    app, _, _ = app_with_responses(tmp_path, [understanding, answer])
    report = app.handle("把苹果放到篮子前面", session_id="front_ok")
    assert report.run_status == "success", report.error
    payload = wire(report)
    assert payload["commands"][5]["parameters"] == {
        "target": payload["commands"][4]["parameters"]["target"],
        "relation": "front", "distance_m": PLACEMENT_EDGE_OFFSET_M}


def test_invented_put_direction_is_stripped_before_export(tmp_path):
    def answer(content):
        binding = content["operations"][0]["role_object_ids"]
        return {"commands": transfer(binding["source"], binding["destination"], relation="front", distance_m=0.1)}

    app, _, requests = app_with_responses(tmp_path, [UNDERSTANDING, answer])
    report = app.handle("把苹果放进篮子", session_id="strip")
    assert report.run_status == "success", report.error
    payload = wire(report)
    assert payload["commands"][5]["parameters"] == {"target": payload["commands"][4]["parameters"]["target"]}
    placement = payload_content(requests[1])["operations"][0]["placement_target"]
    assert placement["relation"] == "inside"
    # The Brain's semantic contract forbids a distance on a placement operation,
    # so an offset in the answer is the model's invention, not a request.
    assert "distance_m" not in placement


NONROBOT = [
    PAUSE,
    {"status": "clarification_required", "turn_kind": "robot_task"},
    {"status": "accepted", "turn_kind": "scene_query", "scene_query": {
        "query_type": "count", "target": "a", "entities": [{"entity_id": "a", "semantic_name": "apple", "category": "fruit"}]}},
    {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "a", "semantic_name": "apple", "category": "fruit"}],
        "operations": [{"operation": "add", "target": "a"}]}},
]


@pytest.mark.parametrize("body", NONROBOT)
def test_nonrobot_never_calls_skill_planner(tmp_path, body):
    app, provider, _ = app_with_responses(tmp_path, [body])
    report = app.handle("test")
    assert report.metrics["understanding_calls"] == 1
    assert report.metrics["skill_planning_calls"] == 0 and report.metrics["planner_used"] is None
    assert len(provider.calls) == 1
    assert report.error is None or report.error.code == "scene_required"


VIOLATIONS = {
    "missing_retreat": (lambda body: body["commands"].pop(), "atomic_plan_missing_retreat"),
    "unspellable_relation": (lambda body: body["commands"][5]["parameters"].update({"relation": "highest"}),
                             "skill_plan_output_invalid"),
    "unknown_target": (lambda body: body["commands"][1]["parameters"].update({"target": 987654}),
                       "atomic_plan_unknown_target"),
    "invented_skill": (lambda body: body["commands"][0].update({"skill_name": "go_home"}), "planner_unknown_skill"),
    "wrong_landing": (lambda body: [item["parameters"].update(target=body["commands"][1]["parameters"]["target"])
                                    for item in body["commands"][4:]], "atomic_plan_put_target_mismatch"),
}


def violation(failure):
    """A round-three answer whose content the guard must refuse."""
    def answer(content):
        value = answer_for(content)
        VIOLATIONS[failure][0](value)
        return value
    return answer


@pytest.mark.parametrize("failure", sorted(VIOLATIONS))
def test_failed_second_stage_has_debug_no_stale_commands_no_scene_mutation(tmp_path, failure):
    broken = violation(failure)
    app, provider, _ = app_with_responses(
        tmp_path, [UNDERSTANDING, answer_for, UNDERSTANDING, broken, broken, PAUSE])
    first = app.handle("把苹果放进篮子", session_id="failure")
    assert first.run_status == "success"
    scene_before = app.get_session("failure").scene.model_dump()
    old_commands = Path(first.artifacts["commands"]).read_bytes()
    failed = app.handle("把苹果放进篮子", session_id="failure")
    assert failed.run_status != "success" and not failed.executed
    assert failed.error.stage == "skill_planning"
    assert failed.error.code == VIOLATIONS[failure][1]
    assert "commands" not in failed.artifacts
    folder = Path(failed.artifacts["debug"])
    assert not (folder.parent / "commands.json").exists()
    assert (folder / "raw_skill_plan.json").is_file()
    assert (folder / "traceback.txt").is_file()
    # One understanding call plus the answer and its single repair turn.
    assert len(json.loads((folder / "model_calls.json").read_text(encoding="utf-8"))) == 3
    assert json.loads((folder / "skill_plan_validation.json").read_text(encoding="utf-8"))["valid"] is False
    assert app.get_session("failure").scene.model_dump() == scene_before
    assert Path(first.artifacts["commands"]).read_bytes() == old_commands
    paused = app.handle("pause", session_id="failure")
    assert paused.metrics["skill_planning_calls"] == 0 and paused.metrics["planner_used"] is None
    assert not (Path(paused.artifacts["debug"]) / "raw_skill_plan.json").exists()
    assert len(provider.calls) == 6


def test_capability_the_control_grammar_lacks_is_refused_before_any_model_call(tmp_path):
    pressing = {**UNDERSTANDING, "operations": [{"type": "press", "target": "b"}]}
    app, provider, requests = app_with_responses(tmp_path, [pressing])
    report = app.handle("按下按钮", session_id="press")
    assert report.error.code == "atomic_capability_unsupported" and report.error.stage == "skill_planning"
    assert len(provider.calls) == 1 and len(requests) == 1


@pytest.mark.parametrize("mode", ["recipe", "auto", "qwen"])
def test_replay_understanding_only_contract(tmp_path, mode):
    from robot_agent_brain.models.replay import ReplayProvider
    path = tmp_path / "replay.json"
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    turn = TaskParseOutput.model_validate(UNDERSTANDING).to_brain_turn("task")
    path.write_text(json.dumps([{"instruction": "task", "turn": turn.model_dump(mode="json")}]), encoding="utf-8")
    # Use the real ReplayProvider's public file format, not a fake planning interface.
    provider = ReplayProvider(path)
    app = BrainApplication(BrainConfig(provider="replay", planner=mode, output_dir=str(tmp_path / "out")), provider=provider)
    report = app.handle("task")
    assert report.metrics["skill_planning_calls"] == 0
    if mode == "qwen":
        assert report.error.code == "skill_planning_provider_missing"
    else:
        assert report.run_status == "success" and report.metrics["planner_used"] == "recipe"
        assert len(wire(report)["commands"]) == 7


def test_planner_configuration_fingerprint_and_cli(tmp_path, monkeypatch):
    from robot_agent_brain.cli import parser
    configs = []
    for mode in ("recipe", "qwen", "auto"):
        configs.append(BrainApplication(BrainConfig(planner=mode, output_dir=str(tmp_path)), provider=Provider(robot())))
        for command, args in (("run", ["test"]), ("chat", []), ("batch", ["--cases", "cases.json"])):
            parsed = parser().parse_args([command, *args, "--planner", mode, "--planner-max-completion-tokens", "512"])
            assert parsed.planner == mode and parsed.planner_max_completion_tokens == 512
    assert len({app.config_fingerprint for app in configs}) == 3
    assert configs[0].config_summary["atomic_skill_planning_prompt_sha256"]
    assert configs[0].config_summary["skill_planning_response_format"] == "json_object"
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"planner": "qwen"}), encoding="utf-8")
    assert BrainConfig.load(path).planner == "qwen"
    monkeypatch.setenv("ROBOT_BRAIN_PLANNER", "auto")
    assert BrainConfig.load(path).planner == "auto"
    assert BrainConfig.load(path, overrides={"planner": "recipe"}).planner == "recipe"
    for cap in (127, 4097):
        with pytest.raises(ValueError):
            BrainConfig(planner_max_completion_tokens=cap)


def test_first_turn_planner_failure_does_not_commit_bootstrap(tmp_path):
    broken = violation("missing_retreat")
    app, _, _ = app_with_responses(tmp_path, [UNDERSTANDING, broken, broken])
    report = app.handle("把苹果放进篮子", session_id="initial-failure")
    assert report.error.stage == "skill_planning"
    assert app.get_session("initial-failure").scene is None
    assert report.scene_commit_status == "unchanged" and not report.scene_created
    assert "commands" not in report.artifacts and "scene_config" not in report.artifacts


def test_collection_expands_before_second_call_and_keeps_dependencies(tmp_path):
    from copy import deepcopy
    understanding = deepcopy(UNDERSTANDING)
    understanding["entities"][0].update(count=2, quantity_mode="all")

    def plan_for(content):
        bindings = [operation["role_object_ids"] for operation in content["operations"]]
        return {"commands": [item for binding in bindings
                             for item in transfer(binding["source"], binding["destination"])]}

    app, _, requests = app_with_responses(tmp_path, [understanding, plan_for])
    report = app.handle("把两个苹果放进篮子")
    assert report.run_status == "success", report.error
    content = json.loads(requests[1]["messages"][1]["content"])
    assert [op["role_bindings"]["source"] for op in content["operations"]] == ["a__01", "a__02"]
    assert content["operations"][1]["depends_on"] == ["op-1__01"]
    # Two operations now mean fourteen commands, so the budget follows the expanded graph.
    assert requests[1]["max_completion_tokens"] == 1024
    payload = wire(report)
    assert len(payload["commands"]) == 14
    assert len({c["parameters"]["target"] for c in payload["commands"] if c["skill_name"] == "pick"}) == 2


def test_second_call_timeout_keeps_failure_record_and_no_false_scene(tmp_path):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(200, json=response(raw=json.dumps(UNDERSTANDING)))
        raise httpx.ReadTimeout("planner timed out", request=request)
    provider = QwenHTTPProvider("http://example/v1", "test", transport=httpx.MockTransport(handler))
    app = BrainApplication(BrainConfig(planner="qwen", debug=True, output_dir=str(tmp_path)), provider=provider)
    report = app.handle("把苹果放进篮子")
    assert report.error.stage == "skill_planning" and report.error.code == "skill_planning_failed"
    assert report.metrics["skill_planning_calls"] == 1 and len(report.metrics["model_calls"]) == 2
    assert report.metrics["model_calls"][1]["status"] == "failed"
    assert "commands" not in report.artifacts and app.get_session(report.session_id).scene is None
    raw = json.loads((Path(report.artifacts["debug"]) / "raw_skill_plan.json").read_text(encoding="utf-8"))
    assert raw["available"] is False
