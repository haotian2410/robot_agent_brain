import json
import httpx
import pytest
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.layout_planning import LayoutPlanningRequest
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.contracts.turn import BrainTurn
from test_layout_transaction import setup


def provider_for(payload, requests):
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)},
                                                     "finish_reason": "stop"}]})
    return QwenHTTPProvider("http://example/v1", "fixture", transport=httpx.MockTransport(respond))


def test_custom_draft_uses_recorded_schema_request_and_samples_to_scene():
    requests = []
    provider = provider_for({"path": [{"u": .2, "v": .5}, {"u": .8, "v": .5}]}, requests)
    scene, spec, editor = setup()
    spec = spec.model_copy(update={"pattern": spec.pattern.model_validate({"kind": "custom", "description": "水平细线"})})
    pipeline = BrainPipeline(provider, editor.assets, scene_editor=editor)
    result = pipeline.process_turn("custom", BrainTurn(status="accepted", turn_kind="scene_layout",
        instruction="六个苹果沿细线排列", arrangement_spec=spec), scene)
    assert len(requests) == 1
    assert result.layout_plan.planner_source == "qwen_draft"
    assert len(result.layout_plan.slots) == len(result.scene_patch.operations) == 6
    assert requests[0]["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert provider.calls[0]["stage"] == "layout_planning"
    assert provider.calls[0]["prompt_sha256"]


@pytest.mark.parametrize("payload", [
    {"path": [{"u": .1, "v": .2}, {"u": 2, "v": .5}]},
    {"path": [{"u": 0, "v": 0}, {"u": 1, "v": 1}, {"u": 0, "v": 1}, {"u": 1, "v": 0}]},
    {"path": [{"u": .1, "v": .2}, {"u": .9, "v": .8}], "xyz": [0, 0, 0]},
    {"path": []},
])
def test_bad_custom_model_draft_is_not_repaired_or_silently_accepted(payload):
    requests = []
    provider = provider_for(payload, requests)
    with pytest.raises(QwenProviderError):
        provider.plan_layout(LayoutPlanningRequest(description="图案", requested_count=3))
    assert len(requests) == 1
