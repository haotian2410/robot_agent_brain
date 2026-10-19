import base64
import json
import struct
import zlib
import httpx
import pytest

pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from robot_agent_brain.web.gateway import GatewayScenePlatformAdapter
from robot_agent_brain.web.protocol import digest
from robot_agent_brain.contracts.camera import CameraRequest
from robot_agent_brain.contracts.scene import SceneComponent
from test_query_scene_continuity import supported_scene


class Browser:
    """Explicit test double, NOT the supplied WebEditor release."""
    def __init__(self, scene=None):
        self.scene = scene or supported_scene()
        self.calls, self.receipt = [], None
        self.fault = None
        self.next_id = max(o.object_id_in_scene for o in self.scene.objects) + 1

    def handle(self, request):
        route = request.url.path
        self.calls.append((request.method,route))
        identity = {"browserID":"b","scene_id":self.scene.scene_id,"scene_version":self.scene.scene_version,
                    "sceneDigest":digest(self.scene),"playback_state":"stopped"}
        if route == "/brainCapabilities":
            return httpx.Response(200,json={"protocol":"brain-web/1","browserID":"b","capabilities":[
                "atomic_commit","versioned_manual_edits","bound_browser","task_edit_lock"]})
        if route == "/acquireSceneLease":
            if self.fault == "lease_timeout":raise httpx.ReadTimeout("lost lease",request=request)
            return httpx.Response(200,json={"browserID":"b","leaseToken":"lease"})
        if route == "/releaseSceneLease":
            return httpx.Response(200,json={"browserID":"b","state":"quarantined" if json.loads(request.content).get("keepLocked") else "released"})
        if route == "/getWorld":
            self.next_id = max(self.next_id, max(o.object_id_in_scene for o in self.scene.objects) + 1)
            headers={"X-World-Source":"live","X-Browser-ID":"b","X-Playback-State":"stopped","X-Scene-Digest":digest(self.scene), "X-Next-Object-ID":str(self.next_id)}
            if self.fault == "cache":headers["X-World-Source"]="cache"
            if self.fault == "browser":headers["X-Browser-ID"]="other"
            if self.fault == "playing":headers["X-Playback-State"]="playing"
            return httpx.Response(200,json=self.scene.model_dump(mode="json"),headers=headers)
        if route == "/commitWorld":
            body=json.loads(request.content)
            if self.fault == "reject":return httpx.Response(409,json={"error":"invalid object"})
            self.scene=type(self.scene).model_validate(body["scene"])
            self.receipt={"transactionID":body["transactionID"],"browserID":"b","status":"committed",
                "scene_id":self.scene.scene_id,"scene_version":self.scene.scene_version,"sceneDigest":digest(self.scene),"rejected_objects":[]}
            if self.fault == "partial":self.receipt['rejected_objects']=[1]
            if self.fault == "wrong_receipt":self.receipt['browserID']='other'
            if self.fault in {"timeout","unknown"}:raise httpx.ReadTimeout("lost acknowledgement",request=request)
            return httpx.Response(200,json=self.receipt)
        if route == "/queryWorldCommit":
            return httpx.Response(404,json={}) if self.fault in {"unknown","reject"} else httpx.Response(200,json=self.receipt)
        if route == "/captureScene":
            def chunk(kind, data):
                return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
            png=(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',640,480,8,2,0,0,0))+
                 chunk(b'IDAT',zlib.compress(b'\x00'*(640*3+1)*480))+chunk(b'IEND',b''))
            data=identity|{"width":640,"height":480,"image_encoding":"png","image_base64":base64.b64encode(png).decode()}
            if self.fault == "stale_frame":data["scene_version"]-=1
            if self.fault == "bad_size":data["width"]=320
            if self.fault == "bad_png":data['image_base64']=base64.b64encode(png[:24]).decode()
            return httpx.Response(200,json=data)
        if route == "/get2DAABB":
            return httpx.Response(200,json=identity|{"width":640,"height":480,"visible":self.fault!="invisible",
                "box":{"x_min":64,"y_min":48,"x_max":128,"y_max":96}})
        raise AssertionError(route)


def adapter(browser, tmp_path=None):
    return GatewayScenePlatformAdapter("http://127.0.0.1:8099","b",camera_id=5,
        journal_dir=tmp_path,client=httpx.Client(transport=httpx.MockTransport(browser.handle)))


@pytest.mark.parametrize("fault",["cache","browser","playing"])
def test_stale_or_wrong_viewer_rejected(fault):
    browser=Browser();browser.fault=fault
    with pytest.raises(ValueError):adapter(browser).adopt(browser.scene)
    assert not any(method=="POST" for method,_ in browser.calls)


@pytest.mark.parametrize("fault",[None,"timeout","unknown","reject"])
def test_commit_receipt_and_timeout_never_resend(tmp_path,fault):
    browser=Browser();platform=adapter(browser,tmp_path);platform.adopt(browser.scene)
    candidate=browser.scene.model_copy(update={"scene_version":1})
    browser.fault=fault
    if fault in {"unknown","reject"}:
        with pytest.raises(ValueError,match="commit_unknown"):platform.load_scene(candidate)
        assert platform.scene.scene_version==0
    else:
        assert platform.load_scene(candidate).scene_version==1
    assert browser.calls.count(("POST","/commitWorld"))==1
    assert not any(route=="/updateWorld" for _,route in browser.calls)
    assert list(tmp_path.glob('*.json'))


def test_multi_object_patch_single_commit():
    from robot_agent_brain.contracts.scene import ScenePatch
    browser=Browser();platform=adapter(browser);platform.adopt(browser.scene)
    patch=ScenePatch(scene_id=1,base_scene_version=0,operations=[{"action":"remove_object","object_id_in_scene":i} for i in (1,2)])
    platform.apply_patch(patch)
    assert browser.calls.count(("POST","/commitWorld"))==1
    assert len(browser.scene.objects)==1


@pytest.mark.parametrize("fault",[None,"stale_frame","bad_size","bad_png","invisible"])
def test_camera_uses_live_bound_scene(fault):
    browser=Browser()
    from test_component_runtime import object_
    camera=object_(5,"camera","sensor")
    camera.components.append(SceneComponent(component_type="Camera",properties={"type":"rgb","resolution":[640,480],"fov":60,"near":.01,"far":10}))
    browser.scene.objects.append(camera)
    # Demo metadata uses untyped refs; explicitly type models for box candidates.
    for o in browser.scene.objects:
        for c in o.components:
            if c.component_type=="MetadataRef":c.properties["type"]="model"
    platform=adapter(browser);platform.adopt(browser.scene);browser.fault=fault
    if fault in {"stale_frame","bad_size","bad_png"}:
        with pytest.raises(ValueError):platform.capture(CameraRequest())
    else:
        frame=platform.capture(CameraRequest())
        assert frame.rgb
        assert bool(frame.instance_boxes)==(fault!="invisible")


@pytest.mark.parametrize('fault',['partial','wrong_receipt'])
def test_partial_or_wrong_commit_never_accepted(tmp_path,fault):
    browser=Browser();platform=adapter(browser,tmp_path);platform.adopt(browser.scene)
    browser.fault=fault
    with pytest.raises(ValueError,match='receipt_invalid'):
        platform.load_scene(browser.scene.model_copy(update={'scene_version':1}))
    assert platform.scene.scene_version==0
    assert browser.calls.count(('POST','/commitWorld'))==1


def test_lost_lease_and_unsupported_camera_are_not_success():
    browser=Browser();platform=adapter(browser);browser.fault='lease_timeout'
    with pytest.raises(httpx.ReadTimeout):platform.acquire_lease(1,browser.scene)
    assert platform.lease_uncertain
    with pytest.raises(ValueError,match='segmentation_unsupported'):
        platform.capture(CameraRequest(outputs=['segmentation']))
    with pytest.raises(ValueError,match='not_configured'):
        platform.capture(CameraRequest(camera_id='wrist'))
