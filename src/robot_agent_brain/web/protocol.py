"""Versioned integration envelopes. Public Scene v1 stays unchanged."""
import hashlib
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig
from ..scene.component_access import SceneIndex

PROTOCOL_VERSION = "brain-web/1"


def digest(scene):
    import rfc8785
    value = scene.model_dump(mode="json") if hasattr(scene, "model_dump") else scene
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def loopback_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}):
        raise ValueError("loopback_http_url_required")
    return url.rstrip("/")


class StartTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=20000)
    scene: SceneConfig
    sessionID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    clientRequestID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    browserID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    sceneDigest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    browserID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    sessionID: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")


def validate_web_scene(scene, joint_inventory=None, reference_registry=None):
    scene = SceneConfig.model_validate(scene.model_dump() if hasattr(scene, "model_dump") else scene)
    if any(x > 2**32-1 for x in [scene.scene_id, scene.scene_version, *[o.object_id_in_scene for o in scene.objects]]):
        raise ValueError("web_uint32_required")
    index = SceneIndex(scene)
    for obj in scene.objects:
        driver = index.robot_driver(obj.object_id_in_scene)
        if driver is None:
            continue
        ref = index.metadata_ref(obj.object_id_in_scene)
        if joint_inventory is not None:
            if index.metadata_type(obj.object_id_in_scene) != "robot" or not ref:
                raise ValueError("robot_joint_inventory_missing")
            inventory = joint_inventory.get("robot:" + ref.rsplit("/", 1)[-1])
            if inventory is None:
                raise ValueError("robot_joint_inventory_missing")
            required = set(driver.joint_sequence) | set(driver.available_connect_joints or [])
            if not required <= set(inventory["joints"]):
                raise ValueError("robot_urdf_joint_unknown")
    if reference_registry is not None:
        reference_registry.validate_scene(scene)
    return scene
