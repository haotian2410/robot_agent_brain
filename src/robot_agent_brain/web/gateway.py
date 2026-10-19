"""Strict, browser-bound ScenePlatformPort. Never falls back to updateWorld."""
import base64
import json
import math
import os
import struct
import tempfile
import uuid
import zlib
from pathlib import Path

import httpx
from ..contracts.camera import CameraFrame, CameraInstanceBox
from ..contracts.scene import SceneSnapshot
from ..scene.component_access import SceneIndex
from ..scene.scene_manager import SceneManager
from .protocol import PROTOCOL_VERSION, digest, loopback_url, validate_web_scene


def durable_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class GatewayScenePlatformAdapter:
    restore_read_only = True

    def __init__(self, base_url, browser_id, *, camera_id=5, joint_inventory=None,
                 reference_registry=None, journal_dir=None, client=None):
        self.base_url = loopback_url(base_url)
        self.browser_id, self.camera_id = browser_id, camera_id
        self.original_camera_id = camera_id
        self.joints, self.references = joint_inventory, reference_registry
        self.journal_dir = Path(journal_dir) if journal_dir else None
        self.client = client or httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
        self.scene = None
        self.receipts = []
        self.lease = None
        self.lease_uncertain = False
        self.next_object_id = 0
        if self.journal_dir and (self.journal_dir / "camera_binding.json").exists():
            self.camera_id = json.loads((self.journal_dir / "camera_binding.json").read_text())["camera_id"]

    def _call(self, method, route, **kwargs):
        if self.lease:
            kwargs["headers"] = {**kwargs.get("headers", {}), "X-Brain-Lease": self.lease}
        response = self.client.request(method, self.base_url + route, **kwargs)
        response.raise_for_status()
        return response

    def acquire_lease(self, task_id, scene):
        # A lost lease ACK may have locked the editor. Never silently continue.
        self.lease_uncertain = True
        value = self._call("POST", "/acquireSceneLease", json={"taskID": task_id,
            "browserID": self.browser_id, "sceneDigest": digest(scene),
            "scene_id": scene.scene_id, "scene_version": scene.scene_version}).json()
        if value.get("browserID") != self.browser_id or not isinstance(value.get("leaseToken"), str) or not value["leaseToken"]:
            raise ValueError("gateway_lease_invalid")
        self.lease = value["leaseToken"]
        self.lease_uncertain = False

    def release_lease(self, *, uncertain=False):
        if self.lease:
            reply = self._call("POST", "/releaseSceneLease", json={"browserID": self.browser_id,
                "leaseToken": self.lease, "keepLocked": uncertain}).json()
            if reply.get("browserID") != self.browser_id or reply.get("state") != ("quarantined" if uncertain else "released"):
                raise ValueError("gateway_unlock_unconfirmed")
            self.lease = None

    def capabilities(self):
        try:
            payload = self._call("GET", "/brainCapabilities", params={"browser_id": self.browser_id}).json()
        except (ValueError, httpx.HTTPError):
            raise ValueError("gateway_protocol_upgrade_required") from None
        if (payload.get("protocol") != PROTOCOL_VERSION or payload.get("browserID") != self.browser_id
                or not {"atomic_commit", "versioned_manual_edits", "bound_browser", "task_edit_lock"} <= set(payload.get("capabilities", []))):
            raise ValueError("gateway_protocol_upgrade_required")
        return payload

    def validate(self, scene):
        return validate_web_scene(scene, self.joints, self.references)

    def read_live(self):
        response = self._call("GET", "/getWorld", params={"browser_id": self.browser_id})
        if response.headers.get("X-World-Source") != "live":
            raise ValueError("gateway_live_world_required")
        if response.headers.get("X-Browser-ID") != self.browser_id:
            raise ValueError("gateway_browser_mismatch")
        if response.headers.get("X-Playback-State") != "stopped":
            raise ValueError("gateway_playback_must_stop")
        scene = self.validate(response.json())
        if response.headers.get("X-Scene-Digest") != digest(scene):
            raise ValueError("gateway_scene_digest_mismatch")
        allocator = response.headers.get("X-Next-Object-ID", "")
        if not allocator.isascii() or not allocator.isdigit() or not max((o.object_id_in_scene for o in scene.objects), default=-1) < int(allocator) <= 2**32:
            raise ValueError("gateway_object_allocator_invalid")
        self.next_object_id = int(allocator)
        return scene

    def remap_camera(self, mapping):
        if str(self.original_camera_id) not in mapping:
            raise ValueError("gateway_camera_remap_missing")
        self.camera_id = mapping[str(self.original_camera_id)]
        if self.journal_dir:
            durable_json(self.journal_dir / "camera_binding.json", {"camera_id": self.camera_id})

    def adopt(self, scene):
        candidate = self.validate(scene)
        if digest(self.read_live()) != digest(candidate):
            raise ValueError("gateway_scene_conflict")
        self.scene = candidate.model_copy(deep=True)
        return SceneSnapshot(scene_id=candidate.scene_id, scene_version=candidate.scene_version)

    def restore_scene(self, scene):
        return self.adopt(scene)

    def _journal(self, transaction, value):
        if self.journal_dir is not None:
            durable_json(self.journal_dir / (transaction + ".json"), value)

    def _check_receipt(self, receipt, transaction, candidate):
        if (receipt.get("transactionID") != transaction or receipt.get("browserID") != self.browser_id
                or receipt.get("status") != "committed" or receipt.get("scene_id") != candidate.scene_id
                or receipt.get("scene_version") != candidate.scene_version or receipt.get("sceneDigest") != digest(candidate)
                or receipt.get("rejected_objects", []) != []):
            raise ValueError("gateway_commit_receipt_invalid")

    def load_scene(self, scene):
        candidate = self.validate(scene)
        self.capabilities()
        previous = self.read_live()
        if self.scene is not None and digest(previous) != digest(self.scene):
            raise ValueError("gateway_scene_conflict")
        if candidate.scene_id == previous.scene_id:
            if candidate.scene_version != previous.scene_version + 1:
                raise ValueError("gateway_target_version_invalid")
        elif candidate.scene_version != 1:
            raise ValueError("gateway_new_scene_version_invalid")
        transaction = uuid.uuid4().hex
        request = {"transactionID": transaction, "browserID": self.browser_id,
            "expected": {"scene_id": previous.scene_id, "scene_version": previous.scene_version, "sceneDigest": digest(previous)},
            "scene": candidate.model_dump(mode="json")}
        record = {"request": request, "status": "prepared"}
        self._journal(transaction, record)
        try:
            receipt = self._call("POST", "/commitWorld", json=request).json()
        except (httpx.TransportError, httpx.HTTPStatusError):
            # Never resend a mutating request. Query the transaction plus world.
            try:
                receipt = self._call("GET", "/queryWorldCommit", params={"transactionID": transaction,
                    "browser_id": self.browser_id}).json()
                self._check_receipt(receipt, transaction, candidate)
            except Exception:
                self._journal(transaction, {**record, "status": "unknown"})
                raise ValueError("gateway_commit_unknown") from None
        try:
            self._check_receipt(receipt, transaction, candidate)
            if digest(self.read_live()) != digest(candidate):
                raise ValueError("gateway_commit_readback_mismatch")
        except Exception:
            self._journal(transaction, {**record, "status": "unknown", "receipt": receipt})
            raise
        self._journal(transaction, {**record, "status": "committed", "receipt": receipt})
        self.receipts.append(receipt)
        self.scene = candidate.model_copy(deep=True)
        return SceneSnapshot(scene_id=candidate.scene_id, scene_version=candidate.scene_version)

    def apply_patch(self, patch):
        if self.scene is None:
            raise ValueError("scene_platform_not_loaded")
        candidate = SceneManager(self.scene).apply_patch(patch)
        return self.load_scene(candidate)

    def _frame_identity(self, value, scene):
        if (value.get("browserID") != self.browser_id or value.get("scene_id") != scene.scene_id
                or value.get("scene_version") != scene.scene_version or value.get("sceneDigest") != digest(scene)
                or value.get("playback_state") != "stopped"):
            raise ValueError("camera_frame_scene_mismatch")

    def capture(self, request):
        if request.camera_id not in {"scene_camera", str(self.camera_id)}:
            raise ValueError("camera_not_configured")
        if "segmentation" in request.outputs:
            raise ValueError("camera_segmentation_unsupported")
        scene = self.read_live()
        if self.scene is None or digest(scene) != digest(self.scene):
            raise ValueError("camera_frame_scene_mismatch")
        camera = SceneIndex(scene).properties(self.camera_id, "Camera")
        if camera is None or tuple(camera.resolution) != (request.width, request.height):
            raise ValueError("camera_resolution_mismatch")
        kind = "rgbd" if camera.type == "rgbd" else "rgb"
        if "depth" in request.outputs and kind != "rgbd":
            raise ValueError("camera_depth_unsupported")
        value = self._call("GET", "/captureScene", params={"id": self.camera_id, "type": kind,
            "browser_id": self.browser_id}).json()
        self._frame_identity(value, scene)
        width, height = value.get("width"), value.get("height")
        if (width, height) != (request.width, request.height) or value.get("image_encoding") != "png":
            raise ValueError("camera_encoding_or_size_invalid")
        rgb = base64.b64decode(value["image_base64"], validate=True)
        if len(rgb) < 24 or rgb[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", rgb[16:24]) != (width, height):
            raise ValueError("camera_png_invalid")
        offset, kinds = 8, []
        while offset + 12 <= len(rgb):
            length = struct.unpack(">I", rgb[offset:offset+4])[0]
            end = offset + length + 12
            if end > len(rgb) or zlib.crc32(rgb[offset+4:end-4]) != struct.unpack(">I", rgb[end-4:end])[0]:
                raise ValueError("camera_png_invalid")
            kinds.append(rgb[offset+4:offset+8])
            offset = end
        if offset != len(rgb) or not kinds or kinds[0] != b"IHDR" or kinds[-1] != b"IEND" or b"IDAT" not in kinds:
            raise ValueError("camera_png_invalid")
        depth = None
        if "depth" in request.outputs:
            if value.get("depth_encoding") != "float32le":
                raise ValueError("camera_depth_encoding_invalid")
            depth = base64.b64decode(value["depth_base64"], validate=True)
            if len(depth) != width * height * 4:
                raise ValueError("camera_depth_size_invalid")
        boxes = []
        index = SceneIndex(scene)
        for obj in scene.objects:
            if index.metadata_type(obj.object_id_in_scene) != "model":
                continue
            box = self._call("GET", "/get2DAABB", params={"id": obj.object_id_in_scene,
                "camera_id": self.camera_id, "browser_id": self.browser_id}).json()
            self._frame_identity(box, scene)
            if (box.get("width"), box.get("height")) != (width, height):
                raise ValueError("camera_box_size_invalid")
            if box.get("visible") is False:
                continue
            coords = box["box"]
            x1, y1, x2, y2 = [coords[k] for k in ("x_min", "y_min", "x_max", "y_max")]
            if not all(math.isfinite(n) for n in (x1,y1,x2,y2)):
                raise ValueError("camera_box_invalid")
            normalized = [max(0, min(1000, round(n / size * 1000))) for n, size in
                          ((y1,height),(x1,width),(y2,height),(x2,width))]
            boxes.append(CameraInstanceBox(scene_object_id=obj.object_id_in_scene, bbox=normalized))
        if digest(self.read_live()) != digest(scene):
            raise ValueError("camera_frame_scene_mismatch")
        frame = CameraFrame(camera_id=str(self.camera_id), scene_id=scene.scene_id, scene_version=scene.scene_version,
            width=width, height=height, rgb=rgb, depth=depth, instance_boxes=boxes)
        if self.journal_dir:
            durable_json(self.journal_dir / ("capture-" + uuid.uuid4().hex + ".json"), value | {"instance_boxes": [b.model_dump() for b in boxes]})
        return frame
