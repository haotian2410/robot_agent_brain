import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, stdin=None):
    return subprocess.run([sys.executable,"-m","robot_agent_brain",*args], input=stdin, text=True,
                          capture_output=True, env={**os.environ,"PYTHONPATH":str(ROOT / "src")})


def test_run_replay_without_scene_and_json_stdout(tmp_path):
    result = cli("run","增加一个苹果","--provider","replay","--replay-file",
                 str(ROOT / "examples/replay/add_apple.json"),"--output-dir",str(tmp_path),"--json")
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["scene_source"] == "generated" and report["provider"] == "replay"
    assert report["executed"] is False
    assert Path(report["artifacts"]["scene_config"]).is_file()


def test_replay_requires_exact_input(tmp_path):
    result = cli("run","不能假装理解这句话","--provider","replay","--replay-file",
                 str(ROOT / "examples/replay/add_apple.json"),"--output-dir",str(tmp_path),"--json")
    assert result.returncode == 4
    assert "commands" not in json.loads(result.stdout)["artifacts"]


def test_schemas_does_not_need_model(tmp_path):
    result = cli("schemas","--output-dir",str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "commands.schema.json").is_file()


def test_chat_json_keeps_prompts_on_stderr(tmp_path):
    result = cli("chat","--provider","replay","--replay-file",str(ROOT / "examples/replay/add_apple.json"),
                 "--output-dir",str(tmp_path),"--json",stdin="增加一个苹果\n/status\n/exit\n")
    assert result.returncode == 0
    assert json.loads(result.stdout)["run_status"] == "success"
    assert "Session:" in result.stderr
