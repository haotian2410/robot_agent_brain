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
@pytest.mark.parametrize('cold_restore', [False, True])
def test_brain_only_uncertain_requires_gateway_proof(tmp_path, monkeypatch, verified, resolution, cold_restore):
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
    if cold_restore:
        service.app.sessions.clear()
        service.binding = None
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
    def recovery_client(**kwargs):
        kwargs.setdefault('transport', httpx.MockTransport(respond))
        return factory(**kwargs)
    monkeypatch.setattr('robot_agent_brain.web.service.httpx.Client',
        recovery_client)
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


def test_unknown_task_effects_are_not_recorded_as_confirmed_empty(tmp_path):
    service, browser = configured(tmp_path)
    sid = service.activate(SessionRequest(browserID='b'))['sessionID']
    session = service._bind(sid)
    service.app.accept_browser_scene(sid, browser.scene)
    request = StartTask(command='把苹果放进篮子', sessionID=sid, browserID='b',
                        clientRequestID='unknown-1', scene=browser.scene,
                        sceneDigest=digest(browser.scene))

    conversation = service._record_conversation_turn(
        request, 'unknown-task',
        {'outcome': 'failed', 'executed': False,
         'reply': '提交回执未知',
         'error': {'code': 'gateway_transport_error'},
         'recovery_context': {'lease_state': 'unknown', 'transactionID': 'tx-1'}},
        digest(session.scene), True)

    assert conversation['chain_state'] == 'blocked_reconciliation'
    turn = session.conversation_memory.recent_turns[-1]
    assert turn.effect_evidence.scene_effect == 'unknown'
    assert turn.effect_evidence.execution_effect == 'unknown'
    assert turn.effect_evidence.lease_state == 'unknown'
