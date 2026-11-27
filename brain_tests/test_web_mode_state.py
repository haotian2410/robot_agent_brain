import asyncio
from aiohttp.test_utils import TestClient, TestServer
from robot_agent_brain.web.service import create_http_app
from robot_agent_brain.web.protocol import SessionRequest
from test_web_service import configured
from test_dual_v4_pipeline import setup
from test_dual_session_pipeline import task


def test_http_session_state_exposes_persisted_mode_not_user_guess(tmp_path):
    async def scenario():
        service, _ = configured(tmp_path)
        sid = service.activate(SessionRequest(browserID="b"))["sessionID"]
        current = setup()
        current.process_turn("first", task("left"))
        current.platform = service._bind(sid).platform
        service.app.sessions[sid] = current
        async with TestClient(TestServer(create_http_app(service))) as client:
            response = await client.get("/sessionState?browser_id=b")
            assert response.status == 200
            value = await response.json()
            assert value["robot_mode_lock"]["mode"] == "dual"
            assert value["robot_mode_lock"]["locked"] is True
            assert value["prompt_route"] == "dual_atomic"
            assert value["session_turn_index"] == 1
            assert value["profile_id"] == "fixture_only"
    asyncio.run(scenario())


def test_http_dual_plan_exports_v41_without_control_execution(tmp_path):
    from robot_agent_brain.web.protocol import digest
    from test_application_artifacts import Provider
    async def scenario():
        service, browser = configured(tmp_path)
        sid = service.activate(SessionRequest(browserID="b"))["sessionID"]
        current = setup()
        current.platform = service._bind(sid).platform
        browser.scene = current.scene
        service.app.sessions[sid] = current
        service.app.pipeline = current.pipeline
        service.app.provider = Provider(task("left"))
        # Understanding belongs to the application provider; skill recipe is
        # already configured on this explicit fixture contract.
        service.app.pipeline.understanding = service.app.provider
        async with TestClient(TestServer(create_http_app(service))) as client:
            response = await client.post("/startTask", json={"sessionID": sid, "browserID": "b",
                "clientRequestID": "dual-http", "command": "左臂抓苹果",
                "scene": current.scene.model_dump(mode="json"), "sceneDigest": digest(current.scene)})
            assert response.status == 200, await response.text()
            identifier = (await response.json())["taskID"]
            for _ in range(200):
                state = await client.get("/queryTaskState", params={"taskID": identifier})
                if (await state.json())["state"] in {"任务完成", "任务失败"}:
                    break
                await asyncio.sleep(.01)
            response = await client.get("/queryTaskResult", params={"taskID": identifier})
            result = await response.json()
            assert result["outcome"] == "plan_ready", {key: value for key, value in result.items() if key in {"error", "error_code", "reply", "outcome"}}
            assert result["executed"] is False
            exported = list(current.exported_commands.values())
            assert len(exported) == 1
            assert exported[0]["schema_version"] == "4.1"
            assert exported[0]["scene_digest"] == digest(current.scene)
            assert exported[0]["commands"][0]["arm"] == "left"
            assert current.pending_execution_request is None
    asyncio.run(scenario())
