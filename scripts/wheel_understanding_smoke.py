"""Run outside the checkout against an installed wheel, without real services."""
import json
import sys
from pathlib import Path
import httpx
import robot_agent_brain
from robot_agent_brain.models.understanding_wire import encode, decode, compact_prompt
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest

module = Path(robot_agent_brain.__file__).resolve()
assert module.is_relative_to(Path(sys.prefix).resolve()), module
value = {"status": "accepted", "turn_kind": "scene_query", "scene_query": {
    "query_type": "count", "target": "apple", "entities": [
        {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}]}}
wire = encode(value)
assert decode(wire)["scene_query"]["target"] == "apple"
assert "u.compact.v1" in compact_prompt(TASK_UNDERSTANDING_PROMPT)
def handler(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(wire)}}]})
provider = QwenHTTPProvider("http://wheel.invalid", "mock", transport=httpx.MockTransport(handler),
                           understanding_wire_format="compact_v1")
assert provider.understand_turn(TaskUnderstandingRequest(instruction="有几个苹果")).scene_query.target == "apple"
print(json.dumps({"wheel_smoke": "passed", "module": str(module), "network": False, "control_called": False}))
