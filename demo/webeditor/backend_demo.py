"""Real Qwen + AgentService HTTP; explicit in-process browser TEST DOUBLE.

No browser rendering, camera, Control, or physical execution is demonstrated.
Run from the checkout with the web extra and the external OLS service installed.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
from aiohttp.test_utils import TestClient, TestServer
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.web.gateway import GatewayScenePlatformAdapter, durable_json
from robot_agent_brain.web.protocol import digest
from robot_agent_brain.web.service import AgentService, create_http_app


class BrowserDouble:
    def __init__(self, scene):
        self.scene = scene
        self.next_id = max(o.object_id_in_scene for o in scene.objects) + 1
        self.receipts = {}

    def handle(self, request):
        route = request.url.path
        if route == "/brainCapabilities":
            return httpx.Response(200, json={"protocol":"brain-web/1", "browserID":"demo-double",
                "capabilities":["atomic_commit","versioned_manual_edits","bound_browser","task_edit_lock"]})
        if route == "/getWorld":
            self.next_id = max(self.next_id, max(o.object_id_in_scene for o in self.scene.objects)+1)
            return httpx.Response(200, json=self.scene.model_dump(mode="json"), headers={
                "X-World-Source":"live", "X-Browser-ID":"demo-double", "X-Playback-State":"stopped",
                "X-Scene-Digest":digest(self.scene), "X-Next-Object-ID":str(self.next_id)})
        if route == "/acquireSceneLease":
            return httpx.Response(200, json={"browserID":"demo-double", "leaseToken":"test-only-lease"})
        if route == "/releaseSceneLease":
            data = json.loads(request.content)
            return httpx.Response(200, json={"browserID":"demo-double",
                "state":"quarantined" if data["keepLocked"] else "released"})
        if route == "/commitWorld":
            body = json.loads(request.content)
            if body["transactionID"] in self.receipts:
                return httpx.Response(200,json=self.receipts[body["transactionID"]])
            if body["expected"] != {"scene_id":self.scene.scene_id,"scene_version":self.scene.scene_version,
                                    "sceneDigest":digest(self.scene)}:
                return httpx.Response(409,json={"error":"conflict"})
            self.scene = SceneConfig.model_validate(body["scene"])
            receipt = {"transactionID":body["transactionID"],"browserID":"demo-double","status":"committed",
                "scene_id":self.scene.scene_id,"scene_version":self.scene.scene_version,
                "sceneDigest":digest(self.scene),"rejected_objects":[]}
            self.receipts[body["transactionID"]] = receipt
            return httpx.Response(200,json=receipt)
        if route == "/queryWorldCommit":
            receipt = self.receipts.get(request.url.params["transactionID"])
            return httpx.Response(200 if receipt else 404,json=receipt or {})
        # Never invent pixels or bounding boxes to make a visual demo pass.
        return httpx.Response(501,json={"error":"browser_double_has_no_camera"})


async def run(args):
    config = BrainConfig.load(args.config, overrides={"output_dir":str(Path(args.output_dir).resolve())})
    browser = BrowserDouble(SceneConfig.model_validate(json.loads(Path(config.default_scene).read_text())))
    service = AgentService(config, joint_inventory=args.joint_inventory, platform_factory=lambda binding:
        GatewayScenePlatformAdapter("http://127.0.0.1:8099", "demo-double", joint_inventory=service.joints,
            reference_registry=service.references, journal_dir=Path(config.output_dir)/binding["id"]/"gateway_transactions",
            client=httpx.Client(transport=httpx.MockTransport(browser.handle))))
    commands = ["增加一个苹果和一个蓝色篮子", "把苹果改成蓝色",
        "查询蓝色苹果的数量", "把蓝色篮子放大一点", "把苹果放大一点", "把蓝色苹果放进篮子"]
    records = []
    expected = ['scene_updated','scene_updated','answered','scene_updated','failed','plan_ready']
    async with TestClient(TestServer(create_http_app(service))) as client:
        response = await client.post('/sessions',json={"browserID":"demo-double"})
        sid = (await response.json())["sessionID"]
        for index, instruction in enumerate(commands, 1):
            before = digest(browser.scene)
            response = await client.post('/startTask',json={"command":instruction, "scene":browser.scene.model_dump(mode="json"),
                "sceneDigest":digest(browser.scene),"sessionID":sid,"browserID":"demo-double","clientRequestID":f"demo-{index}"})
            response.raise_for_status()
            task = (await response.json())["taskID"]
            while True:
                response = await client.get('/queryTaskResult',params={"taskID":task})
                result = await response.json()
                if response.status != 202:
                    break
                await asyncio.sleep(.2)
            unchanged = digest(browser.scene)==before
            records.append({"instruction":instruction,"result":result,"expected_outcome":expected[index-1],
                            "scene_unchanged":unchanged})
            print(json.dumps({"instruction":instruction,"taskID":task,"outcome":result["outcome"],
                "reply":result.get("reply"),"metrics":result.get("metrics")},ensure_ascii=False),flush=True)
            durable_json(Path(config.output_dir)/"demo_report.json", {"qwen":"real","ols":"real",
                "browser":"in_process_test_double","vision":"not_tested","executed":False,"turns":records})
    assert [r['result']['outcome'] for r in records] == expected, 'See demo_report.json for actual failures'
    assert all(records[i]['scene_unchanged'] for i in (2,4,5)), 'Non-edit task changed the scene'


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/webeditor.json')
    parser.add_argument('--joint-inventory',default='var/webeditor/joint_inventory.json')
    parser.add_argument('--output-dir',default='var/webeditor/backend-demo')
    asyncio.run(run(parser.parse_args()))
