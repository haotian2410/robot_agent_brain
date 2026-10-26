import asyncio
import httpx
import pytest
pytest.importorskip("aiohttp", reason="optional web integration dependencies not installed")
pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from aiohttp.test_utils import TestClient, TestServer
from test_web_service import configured
from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
from robot_agent_brain.web.service import create_http_app


@pytest.mark.parametrize('verified', [False, True])
@pytest.mark.parametrize('resolution', ['resume', 'new_session'])
def test_brain_only_uncertain_requires_gateway_proof(tmp_path, monkeypatch, verified, resolution):
    service, browser = configured(tmp_path)
    sid = service.activate(SessionRequest(browserID='b'))['sessionID']
    session = service._bind(sid)
    service.app.accept_browser_scene(sid, browser.scene)
    record, _ = service.tasks.submit(StartTask(command='query', sessionID=sid, browserID='b',
        clientRequestID='failed', scene=browser.scene, sceneDigest=digest(browser.scene)))
    service.tasks.update(record['id'], 'failed', {'outcome':'failed','executed':False,
        'recovery_context':{'lease_state':'unknown','write_attempted':False}}, uncertain=True, terminal=True)
    session.sync_state = 'unknown'
    service.app._save_session(sid)
    calls = []
    def respond(request):
        import json
        payload = json.loads(request.content)
        calls.append(payload)
        assert 'late_write_excluded' not in payload
        return httpx.Response(200, json={'state':'resolved' if verified else 'kept_locked',
            'sessionID':sid,'browserID':'b','taskID':record['id'],
            'sceneDigest':digest(browser.scene),'resolutionID':'verified-fence' if verified else None,
            'retired': resolution == 'new_session',
            'reason':'recovery_write_evidence_missing'})
    factory = httpx.Client
    monkeypatch.setattr('robot_agent_brain.web.service.httpx.Client',
        lambda **kwargs: factory(transport=httpx.MockTransport(respond), **kwargs))
    async def scenario():
        async with TestClient(TestServer(create_http_app(service))) as client:
            response = await client.post('/resolveUncertain', json={'sessionID':sid,'browserID':'b',
                'late_write_excluded':True, 'resolution':resolution})
            value = await response.json()
            assert response.status == 200, value
            assert value['state'] == ('resolved' if verified else 'kept_locked')
            assert bool(service.tasks.binding(sid)['uncertain']) is not verified
    asyncio.run(scenario())
    assert len(calls) == 1 and calls[0]['taskID'] == record['id']
