import asyncio
import importlib.util
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer


def load_stub():
    path = Path(__file__).resolve().parents[1] / "scripts/brain_stub_service.py"
    spec = importlib.util.spec_from_file_location("brain_stub_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stub_accepts_unknown_state_and_returns_synthetic_result():
    async def scenario():
        module = load_stub()
        async with TestClient(TestServer(module.create_app())) as client:
            created = await client.post("/startTask", json={"clientRequestID": "x"})
            payload = await created.json()
            assert payload["terminal"] is False
            task_id = payload["taskID"]
            first = await (await client.get("/queryTaskState", params={"taskID": task_id})).json()
            second = await (await client.get("/queryTaskState", params={"taskID": task_id})).json()
            assert first["state"] == "规划中" and first["terminal"] is False
            assert second["terminal"] is True
            result = await (await client.get("/queryTaskResult", params={"taskID": task_id})).json()
            assert result["synthetic"] is True and result["real_qwen_tested"] is False
    asyncio.run(scenario())
