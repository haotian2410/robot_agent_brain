import json
import httpx
import pytest
from robot_agent_brain.semantics.motion_evidence import resolve_motion_evidence, normalize_scene_motion
from robot_agent_brain.contracts.turn import SceneEditIntent


@pytest.mark.parametrize("text", ["苹果向右移动", "move apple right"])
def test_model_distance_cannot_fill_missing_user_distance(text):
    edit = SceneEditIntent(operation="translate", semantic_name="apple", category="fruit",
                           direction="right", distance_m=.01)
    with pytest.raises(ValueError, match="motion_distance_evidence_missing"):
        normalize_scene_motion(text, edit)


@pytest.mark.parametrize("phrase,scale", [("一点","small"),("一些","medium"),("很多","large"),
                                         ("a little","small"),("some","medium"),("a lot","large")])
def test_scale_requires_matching_language(phrase, scale):
    text = "苹果向右移动" + phrase if not phrase.isascii() else "move apple right " + phrase
    span = resolve_motion_evidence(text, 1)[0]
    assert span.motion_scale == scale and span.distance_m is None


def test_qwen_missing_distance_is_blocked_not_delivery_or_network_failure(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from robot_agent_brain.models.qwen_http import QwenHTTPProvider
    output = {"status":"accepted", "turn_kind":"robot_task",
              "entities":[{"id":"a", "name":"apple", "category":"fruit"}],
              "operations":[{"type":"move", "target":"a", "motion_direction":"right", "distance_m":.01}]}
    provider = QwenHTTPProvider("http://example/v1", "qwen-test", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(output)}, "finish_reason":"stop"}]})))
    app = BrainApplication(BrainConfig(output_dir=str(tmp_path), model="qwen-test"), provider=provider)
    report = app.handle("用机械臂把苹果向右移动")
    assert report.run_status == "blocked" and report.error.code == "motion_distance_evidence_missing"
    assert not report.scene_created and "commands" not in report.artifacts
    assert len(report.metrics["model_calls"]) == 1
