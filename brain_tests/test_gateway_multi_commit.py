"""Two writes inside one task: the base each one commits against.

The supplied browser double in ``test_web_gateway`` always serves its live
world, so it cannot show the failure this file pins: the real local gateway
freezes ``world_snapshot`` when the lease is acquired and an online commit does
not refresh it. A Brain that builds its compare-and-set base from that frozen
copy therefore asks the gateway to replace a world it already replaced itself,
and the gateway answers 409 -- which, mid-write, is an unconfirmed transaction
rather than a clean refusal.

``LeaseGateway`` is transcribed from ``local_gateway.py`` on exactly those
points: ``_read_live_world(use_lease_snapshot=True)``, the ``expected !=
state.scene_identity`` CAS, and the fact that only acquire writes the snapshot.
"""
import copy
import json

import httpx
import pytest

pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.web.gateway import GatewayScenePlatformAdapter
from robot_agent_brain.web.protocol import digest
from test_query_scene_continuity import set_transform, supported_scene


def identity(document):
    return {"scene_id": document.get("scene_id"), "scene_version": document.get("scene_version"),
            "scene_sub_version": document.get("scene_sub_version") or 0,
            "sceneDigest": digest(document)}


class LeaseGateway:
    def __init__(self, scene):
        self.live = scene.model_dump(mode="json")
        self.snapshot = None
        self.receipts = []
        self.posts = 0
        self.connected = True

    def served(self):
        """The browser's own convention: a zero sub-version is an absent key."""
        document = copy.deepcopy(self.live)
        if document.get("scene_sub_version") == 0:
            document.pop("scene_sub_version", None)
        return document

    def error(self, request, status, code, message):
        return httpx.Response(status, request=request,
                              json={"error": {"code": code, "message": message, "request_id": None}})

    def handle(self, request):
        route = request.url.path
        if route == "/brainCapabilities":
            return httpx.Response(200, json={"protocol": "brain-web/2", "browserID": "b",
                                             "capabilities": ["atomic_commit", "sub_versioned_scene_identity",
                                                             "setup_only_local_edits", "bound_browser",
                                                             "task_edit_lock", "canonical_scene",
                                                             "agent_owned_phase", "uncertain_recovery"]})
        if route == "/acquireSceneLease":
            self.snapshot = self.served()
            return httpx.Response(200, json={"browserID": "b", "leaseToken": "lease"})
        if route == "/getWorld":
            frozen = request.url.params.get("lease_snapshot") == "1" and self.snapshot is not None
            if not frozen and not self.connected:
                # The live read is addressed to the bound browser; absent is an answer (503).
                return self.error(request, 503, "NO_BROWSER_CONNECTED",
                                  "no viewer has announced itself on /events")
            document = self.snapshot if frozen else self.served()
            return httpx.Response(200, json=document, headers={
                "X-World-Source": "live", "X-Browser-ID": "b", "X-Playback-State": "stopped",
                "X-Scene-Digest": digest(document),
                "X-Scene-Sub-Version": str(document.get("scene_sub_version") or 0),
                "X-Next-Object-ID": str(max(o["object_id_in_scene"] for o in document["objects"]) + 1)})
        if route == "/commitWorld":
            self.posts += 1
            body = json.loads(request.content)
            current = identity(self.served())
            if body["expected"] != current:
                # The gateway holds the live world; the frozen snapshot is not evidence.
                return self.error(request, 409, "browser_scene_version_conflict",
                                  f"expected {body['expected']} is not the 现场 this gateway holds ({current})")
            self.live = body["scene"]
            committed = identity(self.served())
            receipt = {"transactionID": body["transactionID"], "browserID": "b", "status": "committed",
                       "rejected_objects": [], **committed, "sceneDigest": digest(body["scene"])}
            self.receipts.append(receipt)
            return httpx.Response(200, json=receipt)
        raise AssertionError(route)


@pytest.fixture
def world():
    return LeaseGateway(supported_scene())


@pytest.fixture
def platform(world):
    adapter = GatewayScenePlatformAdapter("http://127.0.0.1:8099", "b", camera_id=5,
        client=httpx.Client(transport=httpx.MockTransport(world.handle)))
    scene = SceneConfig.model_validate(world.served())
    # Acquire for real: freezing the snapshot here is the only thing that makes
    # this world different from the always-live double in test_web_gateway.
    adapter.acquire_lease("task-1", scene)
    adapter.scene = scene
    return adapter


def moved(scene, position):
    candidate = scene.model_copy(deep=True)
    candidate.scene_version += 1
    set_transform(candidate, 1, position=position)
    return candidate


def test_the_second_write_in_one_task_compares_against_the_world_it_replaced(world, platform):
    # One lease, two commits: the versions only climb if each base is the world
    # the task itself last wrote, not the copy frozen when the lease began.
    platform.load_scene(moved(platform.scene, (-.2, .1, .045)))
    platform.load_scene(moved(platform.scene, (-.15, .2, .045)))
    assert [receipt["scene_version"] for receipt in world.receipts] == [1, 2]
    assert world.served()["scene_version"] == 2
    assert platform.scene.scene_version == 2
    # The lease's own copy never moved, so it was not what these writes used.
    assert identity(world.snapshot)["scene_version"] == 0


def test_a_base_that_is_only_the_frozen_snapshot_is_not_a_commit(world, platform):
    # Without this, the pass above would prove nothing about the double.
    platform.load_scene(moved(platform.scene, (-.2, .1, .045)))
    response = world.handle(httpx.Request("POST", "http://127.0.0.1:8099/commitWorld", content=json.dumps({
        "transactionID": "t-2", "browserID": "b", "expected": identity(world.snapshot),
        "change_kind": "scene_edit", "scene": moved(platform.scene, (-.15, .2, .045)).model_dump(mode="json")})
        .encode()))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "browser_scene_version_conflict"
    assert len(world.receipts) == 1


def test_an_edit_that_landed_between_writes_is_still_refused_before_the_post(world, platform):
    platform.load_scene(moved(platform.scene, (-.2, .1, .045)))
    # Somebody else moved the world while the task held the lease.
    world.live = moved(SceneConfig.model_validate(world.served()), (-.3, .3, .045)).model_dump(mode="json")
    with pytest.raises(ValueError, match="gateway_scene_conflict"):
        platform.load_scene(moved(platform.scene, (-.15, .2, .045)))
    assert [receipt["scene_version"] for receipt in world.receipts] == [1]


def test_the_first_write_of_a_task_needs_no_browser_round_trip(world, platform):
    # The lease copy is frozen at acquire precisely so a task can still commit while the editor
    # is reconnecting; only a write that follows this Brain's own commit asks what it replaced.
    # The read back is a separate leg, and the real gateway answers it from its own snapshot.
    world.connected = False
    with pytest.raises(httpx.HTTPStatusError):
        platform.load_scene(moved(platform.scene, (-.2, .1, .045)))
    assert world.posts == 1


def test_a_second_write_with_the_editor_gone_is_refused_before_the_post(world, platform):
    # Once the task has moved the world, the frozen copy is a lie, so the base has to be read
    # live -- and with no browser that read fails before any write, rather than landing a
    # transaction neither side can account for.
    platform.load_scene(moved(platform.scene, (-.2, .1, .045)))
    world.connected = False
    with pytest.raises(httpx.HTTPStatusError):
        platform.load_scene(moved(platform.scene, (-.15, .2, .045)))
    assert world.posts == 1
    assert [receipt["scene_version"] for receipt in world.receipts] == [1]
