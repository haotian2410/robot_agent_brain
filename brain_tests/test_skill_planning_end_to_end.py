import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from test_application_artifacts import Provider, robot
from test_qwen_http import response, PAUSE
from test_skill_planning_qwen import raw_plan


UNDERSTANDING = {
    "status": "accepted", "turn_kind": "robot_task",
    "entities": [{"id": "a", "name": "apple", "category": "fruit"},
                 {"id": "b", "name": "basket", "category": "container"}],
    "operations": [{"type": "pick_and_place", "source": "a", "destination": "b",
                    "placement_target": {"kind": "container_interior", "reference": "b", "relation": "inside"}}],
}


def app_with_responses(tmp_path, bodies, *, mode="qwen", debug=True):
    pending = iter(bodies)
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        body = next(pending)
        return httpx.Response(200, json=response(raw=json.dumps(body)))
    provider = QwenHTTPProvider("http://example/v1", "test-model", transport=httpx.MockTransport(handler))
    app = BrainApplication(BrainConfig(model="test-model", planner=mode, output_dir=str(tmp_path), debug=debug), provider=provider)
    return app, provider, requests


@pytest.mark.parametrize("mode,count,used", [("recipe", 1, "recipe"), ("auto", 1, "recipe"), ("qwen", 2, "qwen")])
def test_http_two_stage_integration_and_commands_schema(tmp_path, mode, count, used):
    app, provider, requests = app_with_responses(tmp_path, [UNDERSTANDING, raw_plan()], mode=mode)
    report = app.handle("把苹果放进篮子", session_id="e2e")
    assert report.run_status == "success", report.error
    assert report.executed is False
    assert report.metrics["understanding_calls"] == 1
    assert report.metrics["skill_planning_calls"] == count - 1
    assert report.metrics["planner_used"] == used and report.metrics["planner_requested"] == mode
    assert len(provider.calls) == len(requests) == count
    payload = json.loads(Path(report.artifacts["commands"]).read_text())
    CommandsFile.model_validate(payload)
    Draft202012Validator(CommandsFile.model_json_schema()).validate(payload)
    assert (payload["scene_id"], payload["scene_version"]) == (report.scene_id, report.scene_version)
    assert [op["operation_id"] for op in payload["operations"]] == ["op-1"]
    assert [c["source_skill_step_id"] for c in payload["commands"]] == [f"step-{i}" for i in range(1, 7)]
    if mode == "qwen":
        folder = Path(report.artifacts["debug"])
        for file in ("planner_context.json", "planner_skill_catalog.txt", "raw_skill_plan.json",
                     "normalized_skill_plan.json", "skill_plan_validation.json"):
            assert (folder / file).is_file()
        assert json.loads((folder / "raw_skill_plan.json").read_text())["operations"][0]["id"] == "op-1"
        assert json.loads((folder / "raw_skill_plan.json").read_text()) == raw_plan()
        assert [c["stage"] for c in report.metrics["model_calls"]] == ["task_understanding", "skill_planning"]


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


@pytest.mark.parametrize("failure", ["unknown_skill", "bad_role", "no_approach", "invalid_schema"])
def test_failed_second_stage_has_debug_no_stale_commands_no_scene_mutation(tmp_path, failure):
    invalid = raw_plan()
    if failure == "unknown_skill":
        invalid["operations"][0]["steps"][0]["skill"] = "go_home"
    elif failure == "bad_role":
        invalid["operations"][0]["steps"][0]["target_role"] = "target"
    elif failure == "no_approach":
        invalid["operations"][0]["steps"].pop(1)
    else:
        invalid["operations"][0]["xyz"] = [1, 2, 3]
    app, provider, _ = app_with_responses(tmp_path, [UNDERSTANDING, raw_plan(), UNDERSTANDING, invalid, PAUSE])
    first = app.handle("把苹果放进篮子", session_id="failure")
    assert first.run_status == "success"
    scene_before = app.get_session("failure").scene.model_dump()
    old_commands = Path(first.artifacts["commands"]).read_bytes()
    failed = app.handle("把苹果放进篮子", session_id="failure")
    assert failed.run_status != "success" and not failed.executed
    assert failed.error.stage == "skill_planning"
    assert "commands" not in failed.artifacts
    folder = Path(failed.artifacts["debug"])
    assert not (folder.parent / "commands.json").exists()
    assert (folder / "raw_skill_plan.json").is_file()
    assert (folder / "traceback.txt").is_file()
    assert len(json.loads((folder / "model_calls.json").read_text())) == 2
    assert json.loads((folder / "skill_plan_validation.json").read_text())["valid"] is False
    assert app.get_session("failure").scene.model_dump() == scene_before
    assert Path(first.artifacts["commands"]).read_bytes() == old_commands
    paused = app.handle("pause", session_id="failure")
    assert paused.metrics["skill_planning_calls"] == 0 and paused.metrics["planner_used"] is None
    assert not (Path(paused.artifacts["debug"]) / "raw_skill_plan.json").exists()
    assert len(provider.calls) == 5


@pytest.mark.parametrize("mode", ["recipe", "auto", "qwen"])
def test_replay_understanding_only_contract(tmp_path, mode):
    from robot_agent_brain.models.replay import ReplayProvider
    path = tmp_path / "replay.json"
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    turn = TaskParseOutput.model_validate(UNDERSTANDING).to_brain_turn("task")
    path.write_text(json.dumps([{"instruction": "task", "turn": turn.model_dump(mode="json")}]))
    # Use the real ReplayProvider's public file format, not a fake planning interface.
    provider = ReplayProvider(path)
    app = BrainApplication(BrainConfig(provider="replay", planner=mode, output_dir=str(tmp_path / "out")), provider=provider)
    report = app.handle("task")
    assert report.metrics["skill_planning_calls"] == 0
    if mode == "qwen":
        assert report.error.code == "skill_planning_provider_missing"
    else:
        assert report.run_status == "success" and report.metrics["planner_used"] == "recipe"


def test_planner_configuration_fingerprint_and_cli(tmp_path, monkeypatch):
    from robot_agent_brain.cli import parser
    configs = []
    for mode in ("recipe", "qwen", "auto"):
        configs.append(BrainApplication(BrainConfig(planner=mode, output_dir=str(tmp_path)), provider=Provider(robot())))
        for command, args in (("run", ["test"]), ("chat", []), ("batch", ["--cases", "cases.json"])):
            parsed = parser().parse_args([command, *args, "--planner", mode, "--planner-max-completion-tokens", "512"])
            assert parsed.planner == mode and parsed.planner_max_completion_tokens == 512
    assert len({app.config_fingerprint for app in configs}) == 3
    assert configs[0].config_summary["skill_planning_prompt_sha256"]
    assert configs[0].config_summary["skill_catalog_sha256"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"planner": "qwen"}))
    assert BrainConfig.load(path).planner == "qwen"
    monkeypatch.setenv("ROBOT_BRAIN_PLANNER", "auto")
    assert BrainConfig.load(path).planner == "auto"
    assert BrainConfig.load(path, overrides={"planner": "recipe"}).planner == "recipe"
    for cap in (127, 4097):
        with pytest.raises(ValueError):
            BrainConfig(planner_max_completion_tokens=cap)


def test_first_turn_planner_failure_does_not_commit_bootstrap(tmp_path):
    invalid = raw_plan()
    invalid["operations"][0]["steps"] = []
    app, _, _ = app_with_responses(tmp_path, [UNDERSTANDING, invalid])
    report = app.handle("把苹果放进篮子", session_id="initial-failure")
    assert report.error.stage == "skill_planning"
    assert app.get_session("initial-failure").scene is None
    assert report.scene_commit_status == "unchanged" and not report.scene_created
    assert "commands" not in report.artifacts and "scene_config" not in report.artifacts


def test_collection_expands_before_second_call_and_keeps_dependencies(tmp_path):
    from copy import deepcopy
    understanding = deepcopy(UNDERSTANDING)
    understanding["entities"][0].update(count=2, quantity_mode="all")
    raw = raw_plan()
    first = raw["operations"][0]
    second = deepcopy(first)
    first["id"], second["id"] = "op-1__01", "op-1__02"
    raw["operations"].append(second)
    app, _, requests = app_with_responses(tmp_path, [understanding, raw])
    report = app.handle("把两个苹果放进篮子")
    assert report.run_status == "success", report.error
    content = json.loads(requests[1]["messages"][1]["content"])
    assert [op["role_bindings"]["source"] for op in content["operations"]] == ["a__01", "a__02"]
    assert content["operations"][1]["depends_on"] == ["op-1__01"]
    assert requests[1]["max_completion_tokens"] == 640
    commands = json.loads(Path(report.artifacts["commands"]).read_text())
    assert len(commands["commands"]) == 12
    assert len({c["parameters"]["target"] for c in commands["commands"] if c["skill_name"] == "grasp"}) == 2


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
    raw = json.loads((Path(report.artifacts["debug"]) / "raw_skill_plan.json").read_text())
    assert raw["available"] is False
