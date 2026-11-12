import json
from pathlib import Path
import httpx
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from test_application_artifacts import Provider, robot


def test_debug_and_checkpoint_include_reproducible_nonsecret_config(tmp_path):
    config = BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path), debug=True, api_key="sensitive-key")
    app = BrainApplication(config, provider=Provider(robot()))
    report = app.handle("two apples", session_id="debug")
    assert report.run_status == "success"
    folder = Path(report.artifacts["commands"]).parent
    record = json.loads((folder / "request_record.json").read_text(encoding="utf-8"))
    state = json.loads((folder.parent / "session_state.json").read_text(encoding="utf-8"))
    assert record["config_fingerprint"] == state["config_fingerprint"] == app.config_fingerprint
    assert record["config"]["demo_assets"] is True
    for name in ("brain_turn", "task_intent", "grounded_task", "normalized_skill_plan",
                 "skill_plan_validation", "model_calls"):
        assert (folder / "debug" / (name + ".json")).is_file()
    for path in tmp_path.rglob("*.json"):
        assert "sensitive-key" not in path.read_text(encoding="utf-8")


def test_raw_failed_response_only_saved_in_debug_and_redacted(tmp_path):
    for debug in (False, True):
        directory = tmp_path / str(debug)
        provider = QwenHTTPProvider("http://example/v1", "qwen-test", api_key="sensitive-key",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
                "choices":[{"message":{"content":'{"broken":"sensitive-key"'},"finish_reason":"length"}],
                "usage":{"total_tokens":20}})))
        app = BrainApplication(BrainConfig(model="qwen-test", output_dir=str(directory), debug=debug, api_key="sensitive-key"), provider=provider)
        report = app.handle("test", session_id="failed")
        assert report.run_status == "failed" and "commands" not in report.artifacts
        assert report.metrics["model_calls"][0]["total_tokens"] == 20
        raw_files = list(directory.rglob("raw_model_response.txt"))
        assert bool(raw_files) == debug
        if debug:
            assert "[REDACTED]" in raw_files[0].read_text(encoding="utf-8")
        assert "sensitive-key" not in report.model_dump_json()
        for path in directory.rglob("*"):
            if path.is_file():
                assert "sensitive-key" not in path.read_text(encoding="utf-8")


def test_raw_model_response_is_scoped_to_the_turn_that_produced_it(tmp_path):
    # A clarification-only turn used to carry the previous turn's
    # ``skill_planning`` blob into its own debug folder, because one provider
    # serves every turn and only ever replaced the stage it actually ran.
    from robot_agent_brain.models.qwen_http import QwenHTTPProvider

    task = {"status": "accepted", "turn_kind": "robot_task", "relations": [],
            "entities": [{"id": "a", "name": "apple", "category": "fruit"},
                         {"id": "t", "name": "table", "category": "surface"}],
            "operations": [{"type": "pick_and_place", "source": "a", "destination": "t",
                            "placement_target": {"kind": "support_surface", "reference": "t"}}]}
    clarification = {"status": "clarification_required", "turn_kind": "robot_task",
                     "clarification_question": "你想把它放到哪里？", "entities": [],
                     "operations": [], "relations": []}
    answers = iter([task] + [clarification] * 8)
    provider = QwenHTTPProvider("http://example/v1", "qwen-test", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [
            {"message": {"content": json.dumps(next(answers))}, "finish_reason": "stop"}]})))
    app = BrainApplication(BrainConfig(model="qwen-test", output_dir=str(tmp_path), debug=True),
                           provider=provider)
    first = app.handle("把苹果放到桌上", session_id="bleed")
    second = app.handle("把苹果放到桌上", session_id="bleed")
    dumped = {path.parent.parent.name: json.loads(path.read_text(encoding="utf-8"))
              for path in tmp_path.rglob("raw_model_response.txt")}
    assert "skill_planning" in dumped[first.request_id]
    assert list(dumped[second.request_id]) == ["turn_id", "task_understanding"]
    assert dumped[first.request_id]["turn_id"] == first.request_id
    assert dumped[second.request_id]["turn_id"] == second.request_id


def test_prompt_json_examples_validate_with_the_actual_parser():
    from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    examples = [json.loads(line) for line in TASK_UNDERSTANDING_PROMPT.splitlines() if line.startswith('{"status"')]
    assert len(examples) >= 5
    for value in examples:
        TaskParseOutput.model_validate(value)
    assert "全部移动没有明确距离时仍须写 motion_scale" not in TASK_UNDERSTANDING_PROMPT


def test_changed_config_is_reported_without_rebuilding_scene(tmp_path):
    first = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path)), provider=Provider(robot()))
    original = first.handle("two apples", session_id="changed")
    second = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path), seed=99), provider=Provider(robot()))
    report = second.handle("two apples", session_id="changed")
    assert report.scene_id == original.scene_id and report.scene_source == "session"
    assert any("configuration_changed_since_restore" in value for value in report.assumptions)
