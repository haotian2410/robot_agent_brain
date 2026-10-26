"""Cross-repository HTTP contract; skipped when the frontend checkout is absent."""
import asyncio
import sys
from pathlib import Path
import pytest
pytest.importorskip("aiohttp", reason="optional web integration dependencies not installed")
pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from aiohttp.test_utils import TestClient, TestServer
from test_web_service import configured
from robot_agent_brain.web.service import create_http_app
from robot_agent_brain.web.protocol import digest


def test_real_brain_http_envelope_is_consumed_by_gateway(tmp_path):
    frontend = Path(__file__).resolve().parents[2] / "web-frontend-master"
    if not (frontend / "local_gateway.py").exists():
        pytest.skip("cross-repository Gateway checkout unavailable")
    sys.path.insert(0, str(frontend))
    try:
        from local_gateway import agent_artifact_names
    finally:
        sys.path.remove(str(frontend))

    async def scenario():
        service, browser = configured(tmp_path)
        async with TestClient(TestServer(create_http_app(service))) as client:
            sid = (await (await client.post('/sessions', json={'browserID':'b'})).json())['sessionID']
            task = await client.post('/startTask', json={'sessionID':sid, 'browserID':'b',
                'clientRequestID':'cross-repo', 'command':'把苹果向右移动10厘米',
                'scene':browser.scene.model_dump(mode='json'), 'sceneDigest':digest(browser.scene)})
            task_id = (await task.json())['taskID']
            for _ in range(100):
                state = await (await client.get('/queryTaskState', params={'taskID':task_id})).json()
                if state['terminal']:
                    break
                await asyncio.sleep(.01)
            result = await (await client.get('/queryTaskResult', params={'taskID':task_id})).json()
            names = agent_artifact_names(result['artifacts'])
            assert set(names) == {'scene_config', 'scene_patch'}
            assert result['executed'] is False
            for artifact in result['artifacts']:
                assert (await client.get(artifact['url'])).status == 200
            assert (await client.get(f'/tasks/{task_id}/artifacts/session_state')).status == 404
    asyncio.run(scenario())
