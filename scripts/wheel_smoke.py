"""Run with a freshly installed wheel's Python, from outside the checkout."""
import json
import os
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

import robot_agent_brain
from jsonschema import Draft202012Validator
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT


def main():
    checkout = Path(__file__).resolve().parents[1]
    installed = Path(robot_agent_brain.__file__).resolve()
    assert not installed.is_relative_to(checkout), installed
    assert not Path.cwd().resolve().is_relative_to(checkout), Path.cwd()
    assert installed.is_relative_to(Path(sys.prefix).resolve()), installed
    assert TASK_UNDERSTANDING_PROMPT
    assert files("robot_agent_brain.resources").joinpath("config.json").is_file()
    config = BrainConfig()
    assert config.load_assets() and config.load_defaults()
    environment = {key:value for key,value in os.environ.items() if key != "PYTHONPATH" and not key.startswith("ROBOT_BRAIN_")}
    executable = Path(sys.executable).parent / "robot-brain"
    directory = Path(tempfile.mkdtemp(prefix="brain-wheel-smoke-"))
    def run(*args):
        result = subprocess.run([str(executable), *args], cwd=directory, env=environment,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        return result.stdout
    assert "run" in run("--help")
    run("schemas", "--output-dir", str(directory / "schemas"))
    schema = json.loads((directory / "schemas" / "commands.schema.json").read_text())
    assert schema == CommandsFile.model_json_schema()
    instruction = "把两个苹果放进篮子"
    fixture = [{"instruction":instruction, "turn":{"status":"accepted", "turn_kind":"robot_task", "instruction":instruction,
        "task_intent":{"instruction":instruction,
            "entities":[{"entity_id":"a", "semantic_name":"apple", "category":"fruit", "count":2, "quantity_mode":"all"},
                        {"entity_id":"b", "semantic_name":"basket", "category":"container"}],
            "operations":[{"operation_id":"op-1", "task_type":"pick_and_place", "source":"a", "destination":"b",
                "placement_target":{"kind":"container_interior", "reference":"b", "relation":"inside"}}]}}}]
    replay = directory / "replay.json"
    replay.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    common = ["--provider", "replay", "--replay-file", str(replay), "--output-dir", str(directory / "out"), "--session", "wheel-session", "--json"]
    first = json.loads(run("run", instruction, *common))
    assert first["run_status"] == "success" and first["scene_source"] == "generated"
    assert first["provider"] == "replay" and first["executed"] is False
    assert first["metrics"]["understanding_calls"] == 1
    commands = json.loads(Path(first["artifacts"]["commands"]).read_text())
    scene = json.loads(Path(first["artifacts"]["scene_config"]).read_text())
    Draft202012Validator(schema).validate(commands)
    assert (commands["scene_id"], commands["scene_version"]) == (scene["scene_id"],scene["scene_version"])
    assert sum(o["semantic_name"] == "apple" for o in scene["objects"]) == 2
    second = json.loads(run("run", instruction, *common))
    assert second["scene_source"] == "session" and second["scene_id"] == first["scene_id"]
    assert second["scene_version"] == first["scene_version"]
    assert second["run_status"] == "success" and second["request_id"] != first["request_id"]
    print(json.dumps({"wheel_smoke":"passed", "installed_module":str(installed), "artifacts":str(directory),
                      "provider":"replay", "real_qwen_tested":False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
