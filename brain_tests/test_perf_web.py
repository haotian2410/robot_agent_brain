"""Mock Web instrumentation parity, not real Qwen/Control performance results."""
import asyncio
import json
import pytest

from aiohttp.test_utils import TestClient, TestServer
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.web.protocol import digest
from robot_agent_brain.web.service import AgentService, create_http_app
from test_web_gateway import Browser, adapter
from test_scene_replace import plan
from test_application_artifacts import Provider


@pytest.mark.parametrize("failure", [False, True])
def test_trace_queue_worker_and_idempotency_leave_scene_result_unchanged(tmp_path, monkeypatch, failure):
    async def scenario(flag):
        monkeypatch.setenv("ROBOT_BRAIN_PERF_TRACE",flag)
        output=tmp_path/flag
        monkeypatch.setenv("PERF_TRACE_OUTPUT_DIR",str(output/"trace"))
        browser=Browser()
        turn=BrainTurn(status="accepted",turn_kind="scene_edit",instruction="把苹果向右移动10厘米",
            scene_edit=plan([{"operation":"translate","target":"old","direction":"right","distance_m":.1}]))
        class MeasuredProvider(Provider):
            def understand_turn(self, request):
                if failure:
                    from robot_agent_brain.models.qwen_http import QwenProviderError
                    self.count += 1
                    raise QwenProviderError("diagnostic mock failure")
                return super().understand_turn(request)
        provider = MeasuredProvider(turn)
        service=AgentService(BrainConfig(provider="replay",planner="qwen",scene_id_bits=32,
            scene_platform_object_ids={0},output_dir=str(output/"tasks"),debug=True),provider=provider,
            platform_factory=lambda binding:adapter(browser,output/binding["id"]/"journal"))
        async with TestClient(TestServer(create_http_app(service))) as client:
            response=await client.post("/sessions",json={"browserID":"b"})
            sid=(await response.json())["sessionID"]
            payload={"sessionID":sid,"clientRequestID":"same","browserID":"b",
                "scene":browser.scene.model_dump(mode="json"),"sceneDigest":digest(browser.scene),"command":turn.instruction}
            response=await client.post("/startTask",json=payload)
            assert response.status==200,await response.text()
            identifier=(await response.json())["taskID"]
            await service.queue.join()
            response=await client.get("/queryTaskResult",params={"taskID":identifier})
            result=await response.json()
            assert result["outcome"] == ("failed" if failure else "scene_updated")
            calls_before = provider.count
            repeated=await client.post("/startTask",json=payload)
            assert (await repeated.json())["taskID"]==identifier
            await service.queue.join()
            assert provider.count == calls_before
            assert browser.calls.count(("POST","/commitWorld")) == (0 if failure else 1)
        files=list((output/"trace").glob("*/spans.jsonl"))
        if flag=="1":
            traces=[[json.loads(line) for line in path.read_text().splitlines()] for path in files]
            main=next(rows for rows in traces if any(s["name"]=="web.execute" for s in rows))
            names=[s["name"] for s in main]
            required = {"web.accept","web.queue.wait","web.execute","web.child_step","web.playback_upload"}
            if not failure:
                required |= {"scene.edit", "store.save", "gateway.commit"}
            assert required <= set(names)
            assert len({s["trace_id"] for s in main})==1
            assert names.count("web.execute")==1
            assert len(traces)==2
        else:
            assert not files
        return browser.scene.model_dump(mode="json"),result["outcome"],result["executed"]
    assert asyncio.run(scenario("0"))==asyncio.run(scenario("1"))
