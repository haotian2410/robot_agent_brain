import json

from robot_agent_brain.contracts.camera import CameraFrame
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenStageRequest
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest
from robot_agent_brain.models.vision_grounding import VisionEntity
from robot_agent_brain.planning.context_builder import build_planner_context

from scripts.qwen_stage_benchmark import StageCase, _assert_understanding_fixed_context, _summarize
from test_skill_planning_context import placement_task


def test_stage_request_builders_keep_production_wire_shapes():
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
                               skill_planning_response_format="json_object")
    understanding = provider.build_understanding_request(
        TaskUnderstandingRequest(instruction="pause")
    ).payload(provider.model)
    assert understanding["response_format"]["type"] == "json_schema"
    assert understanding["response_format"]["json_schema"]["name"] == "task_understanding"
    assert json.loads(understanding["messages"][1]["content"])["instruction"] == "pause"

    frame = CameraFrame(scene_id=1, scene_version=1, camera_id="scene_camera",
                        width=1, height=1, rgb=b"real-fixture")
    vision = provider.build_vision_request(frame, [VisionEntity(entity_id="a", semantic_name="apple")]).payload(provider.model)
    assert vision["response_format"]["type"] == "json_schema"
    assert vision["messages"][1]["content"][0]["type"] == "text"
    assert vision["messages"][1]["content"][1]["type"] == "image_url"
    assert vision["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    atomic = provider.build_atomic_planning_request(
        build_planner_context(placement_task(), include_scene_ids=True)
    ).payload(provider.model)
    assert atomic["response_format"] == {"type": "json_object"}
    assert atomic["max_completion_tokens"] == 768

    off = QwenHTTPProvider("http://example/v1", "qwen-test", structured_output=False)
    off_payload = off.build_understanding_request(
        TaskUnderstandingRequest(instruction="pause")
    ).payload(off.model)
    assert "response_format" not in off_payload


def test_stage_summary_counts_contract_failures_in_throughput():
    values = [
        {"stage": "task_understanding", "input_kind": "simple", "concurrency": 2,
         "warmup": False, "status_code": 200, "contract_status": "succeeded",
         "elapsed_seconds": .5, "http_ttfb_nonstream_seconds": .4,
         "prompt_tokens": 100, "completion_tokens": 20, "wave_wall_seconds": .6, "error": None},
        {"stage": "task_understanding", "input_kind": "simple", "concurrency": 2,
         "warmup": False, "status_code": 200, "contract_status": "failed",
         "elapsed_seconds": .7, "http_ttfb_nonstream_seconds": .6,
         "prompt_tokens": 100, "completion_tokens": 5, "wave_wall_seconds": .6, "error": "provider_output_schema_invalid"},
    ]
    rows = _summarize(values, [])
    assert rows[0]["requests"] == 2
    assert rows[0]["http_success"] == 2
    assert rows[0]["contract_success"] == 1
    assert rows[0]["contract_success_rate"] == .5
    assert rows[0]["requests_per_second"] == 2 / .6


def test_understanding_variants_share_fixed_context_hash():
    request = QwenStageRequest(
        stage="task_understanding", prompt="fixed-system", content=json.dumps({
            "instruction": "one", "asset_catalog": {"revision": "r1"},
            "workspace": {"mode": "tabletop"}, "scene_context": {"scene_id": 3},
        }), schema={"type": "object"}, response_format="json_schema")
    other = QwenStageRequest(
        stage="task_understanding", prompt="fixed-system", content=json.dumps({
            "instruction": "two", "asset_catalog": {"revision": "r1"},
            "workspace": {"mode": "tabletop"}, "scene_context": {"scene_id": 3},
        }), schema={"type": "object"}, response_format="json_schema")
    result = _assert_understanding_fixed_context([
        StageCase("task_understanding", "simple", request, {}),
        StageCase("task_understanding", "multi", other, {}),
    ])
    assert result["instruction_variants"] == ["simple", "multi"]
