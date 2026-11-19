"""Installed-wheel smoke: Qwen HTTP mock, strict atomic plan, no recipe/Control."""
import argparse
import json
from pathlib import Path
import sys
import httpx
import robot_agent_brain
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.models.failure_context import FailureContextDecision
from robot_agent_brain.planning.atomic_planner import AtomicPlanner
from robot_agent_brain.semantics.recovery_routing import continuation_candidate
from robot_agent_brain.web.ols_snapshot import VerifiedOLSSnapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--skill", type=Path, required=True)
    args = parser.parse_args()
    installed = Path(robot_agent_brain.__file__).resolve()
    checkout = Path(__file__).resolve().parents[1]
    assert not installed.is_relative_to(checkout)
    assert installed.is_relative_to(Path(sys.prefix).resolve())
    assert not Path.cwd().resolve().is_relative_to(checkout)
    old = json.loads((args.evidence/"commands.json").read_text())
    task = GroundedTask.model_validate_json((args.evidence/"debug/grounded_task.json").read_text())
    scene = SceneConfig.model_validate_json((args.evidence/"scene_config.json").read_text())
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert "Brain 规划阶段专用输出格式" in payload["messages"][0]["content"]
        return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps({"commands":old["commands"]})},"finish_reason":"stop"}]})
    provider = QwenHTTPProvider("http://wheel.invalid/v1", "wheel-http-mock",
        atomic_skill_prompt_path=args.skill, transport=httpx.MockTransport(handler))
    planner = AtomicPlanner(mode="qwen", provider=provider)
    result = planner.plan("wheel-smoke",task,scene)
    assert len(calls)==1 and result.request_id=="wheel-smoke"
    assert result.scene_id==scene.scene_id
    assert continuation_candidate("左边的") and not continuation_candidate("删除它")
    assert not VerifiedOLSSnapshot.from_verified_records({}, "http://localhost").reusable
    try:
        FailureContextDecision(decision="revise_task",source_turn_id="real-turn")
    except ValueError:
        pass
    else:
        raise AssertionError("missing instruction accepted")
    print(json.dumps({"wheel_smoke":"passed", "installed_module":str(installed),
        "planner":"qwen", "transport":"mock", "real_model":False,
        "command_count":len(result.commands), "control_called":False}))


if __name__ == "__main__":
    main()
