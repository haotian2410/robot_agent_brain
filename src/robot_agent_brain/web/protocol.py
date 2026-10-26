"""brain-web/2 integration envelopes and lossless Scene parsing."""
import hashlib
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig, SceneDocument, parse_scene_document
from ..scene.component_access import SceneIndex

PROTOCOL_VERSION = "brain-web/2"


def digest(scene):
    import rfc8785
    if isinstance(scene, SceneDocument):
        value = scene.raw
    elif hasattr(scene, "raw_document"):
        value = scene.raw_document()
    else:
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
    scene: dict | SceneConfig
    scene_id: int | None = None
    scene_version: int | None = None
    scene_sub_version: int = 0
    sessionID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    clientRequestID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    browserID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    sceneDigest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    browserID: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    sessionID: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    camera_id: int | None = Field(default=None, ge=0, le=2**32 - 1)
    allowActiveTask: bool = False
    scene: dict | None = None


def validate_web_scene(scene, joint_inventory=None, reference_registry=None):
    # A typed SceneConfig can be a prospective, in-memory edit.  Re-parsing
    # its frozen raw document would silently discard those edits (and made
    # joint/uint32 validation inspect stale values).  Raw dictionaries still
    # take the lossless parser path; SceneDocument keeps its typed view.
    if isinstance(scene, SceneDocument):
        document = scene
        scene = document.view
        if document.rejected_objects:
            scene._rejected_objects = document.rejected_objects
    elif isinstance(scene, SceneConfig):
        document = None
        # Validate the current typed values before any digest/raw handling.
    else:
        document = parse_scene_document(scene.raw_document() if hasattr(scene, "raw_document") else scene)
        scene = document.view
        if document.rejected_objects:
            scene._rejected_objects = document.rejected_objects
    if any(x > 2**32-1 for x in [scene.scene_id, scene.scene_version, scene.scene_sub_version,
                                  *[o.object_id_in_scene for o in scene.objects]]):
        raise ValueError("web_uint32_required")
    index = SceneIndex(scene)
    for obj in scene.objects:
        driver = index.robot_driver(obj.object_id_in_scene)
        if driver is None:
            continue
        ref = index.metadata_ref(obj.object_id_in_scene)
        if joint_inventory is not None:
            asset_type = index.metadata_type(obj.object_id_in_scene)
            if asset_type not in {"model", "robot"} or not ref:
                raise ValueError("robot_joint_inventory_missing")
            identifier = ref.rsplit("/", 1)[-1]
            inventory_key = f"{asset_type}:{identifier}"
            required = set(driver.joint_sequence) | set(driver.available_connect_joints or [])
            # OLS 1.0.5 represents articulated passive assets (for example a
            # table or cabinet) with RobotDriver too.  Empty passive drivers
            # need no URDF inventory; non-empty drivers use the typed model
            # namespace just like robot drivers use robot:<id>.
            if not required:
                continue
            inventory = joint_inventory.get(inventory_key)
            if inventory is None:
                if asset_type == "robot":
                    raise ValueError("robot_joint_inventory_missing")
                raise ValueError(f"model_{identifier}_joint_inventory_missing")
            missing = sorted(required - set(inventory["joints"]))
            if missing:
                if asset_type == "robot":
                    raise ValueError("robot_urdf_joint_unknown:" + ",".join(missing))
                raise ValueError(f"model_{identifier}_joint_unknown:" + ",".join(missing))
    if reference_registry is not None:
        reference_registry.validate_scene(scene)
    return scene
