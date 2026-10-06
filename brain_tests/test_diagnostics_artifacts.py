import json
from pathlib import Path
import httpx
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from test_application_artifacts import Provider, robot


def test_debug_and_checkpoint_include_reproducible_nonsecret_config(tmp_path):
    config = BrainConfig(provider="replay", output_dir=str(tmp_path), debug=True, api_key="sensitive-key")
    app = BrainApplication(config, provider=Provider(robot()))
    report = app.handle("two apples", session_id="debug")
    assert report.run_status == "success"
    folder = Path(report.artifacts["commands"]).parent
    record = json.loads((folder / "request_record.json").read_text())
    state = json.loads((folder.parent / "session_state.json").read_text())
    assert record["config_fingerprint"] == state["config_fingerprint"] == app.config_fingerprint
    assert record["config"]["demo_assets"] is True
    for name in ("brain_turn", "task_intent", "grounded_task", "skill_plan", "model_calls"):
        assert (folder / "debug" / (name + ".json")).is_file()
    for path in tmp_path.rglob("*.json"):
        assert "sensitive-key" not in path.read_text()


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
            assert "[REDACTED]" in raw_files[0].read_text()
        assert "sensitive-key" not in report.model_dump_json()
        for path in directory.rglob("*"):
            if path.is_file():
                assert "sensitive-key" not in path.read_text()


def test_prompt_json_examples_validate_with_the_actual_parser():
    from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    examples = [json.loads(line) for line in TASK_UNDERSTANDING_PROMPT.splitlines() if line.startswith('{"status"')]
    assert len(examples) >= 5
    for value in examples:
        TaskParseOutput.model_validate(value)
    assert "全部移动没有明确距离时仍须写 motion_scale" not in TASK_UNDERSTANDING_PROMPT


def test_changed_config_is_reported_without_rebuilding_scene(tmp_path):
    first = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)), provider=Provider(robot()))
    original = first.handle("two apples", session_id="changed")
    second = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path), seed=99), provider=Provider(robot()))
    report = second.handle("two apples", session_id="changed")
    assert report.scene_id == original.scene_id and report.scene_source == "session"
    assert any("configuration_changed_since_restore" in value for value in report.assumptions)
