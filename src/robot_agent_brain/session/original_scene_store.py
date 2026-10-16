"""Write-once original scene with a hash-checked manifest (caller holds session lock)."""
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig, SceneId
from ..contracts.robot_setup import RobotSetup
from ..adapters.scene_file_codec import SceneFileCodec


class OriginalSceneManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    scene_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_request_id: str
    source: str
    task_object_ids: list[SceneId] = Field(min_length=1)
    platform_object_ids: list[SceneId]
    robot_setup: RobotSetup | None = None
    profile_object_map: dict[str, SceneId] | None = None
    config_fingerprint: str | None = None


class OriginalSceneStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def load(self, expected=None):
        try:
            paths = [self.directory / name for name in ("original_scene.json", "original_scene_manifest.json")]
            if any(p.is_symlink() for p in paths):
                raise ValueError("snapshot_symlink")
            scene_bytes = paths[0].read_bytes()
            manifest = OriginalSceneManifest.model_validate_json(paths[1].read_bytes())
            if hashlib.sha256(scene_bytes).hexdigest() != manifest.scene_sha256:
                raise ValueError("snapshot_hash_mismatch")
            if expected is not None and manifest != expected:
                raise ValueError("snapshot_manifest_mismatch")
            scene = SceneConfig.model_validate_json(scene_bytes)
            ids = {o.object_id_in_scene for o in scene.objects}
            tasks, platform = set(manifest.task_object_ids), set(manifest.platform_object_ids)
            if tasks & platform or tasks | platform != ids:
                raise ValueError("snapshot_manifest_objects_invalid")
            return scene, manifest
        except (OSError, ValueError) as exc:
            raise ValueError("original_scene_unavailable: " + str(exc)) from exc

    def capture_once(self, scene, *, platform_object_ids, request_id, source, robot_setup=None, config_fingerprint=None, profile_object_map=None):
        paths = [self.directory / name for name in ("original_scene.json", "original_scene_manifest.json")]
        if any(p.exists() or p.is_symlink() for p in paths):
            # A partial write is an explicit recovery case, never permission to
            # overwrite the first scene with the newest scene.
            return self.load()[1]
        if platform_object_ids is None:
            return None
        ids = {o.object_id_in_scene for o in scene.objects}
        if not set(platform_object_ids) <= ids:
            raise ValueError("original_scene_platform_manifest_invalid")
        task_ids = ids - set(platform_object_ids)
        if not task_ids:
            return None
        payload = json.dumps(SceneFileCodec.payload(scene), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        manifest = OriginalSceneManifest(snapshot_id=uuid.uuid4().hex, scene_sha256=hashlib.sha256(payload).hexdigest(),
            source_request_id=request_id, source=source, task_object_ids=sorted(task_ids),
            platform_object_ids=sorted(platform_object_ids), robot_setup=robot_setup, config_fingerprint=config_fingerprint,
            profile_object_map={str(k): v for k, v in profile_object_map.items()} if profile_object_map is not None else None)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._write_once(paths[0], payload)
        self._write_once(paths[1], manifest.model_dump_json(indent=2).encode())
        return self.load(manifest)[1]

    @staticmethod
    def _write_once(path, payload):
        fd, temp = tempfile.mkstemp(prefix=".original-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temp, path)  # atomic no-replace, including existing symlinks
        finally:
            Path(temp).unlink(missing_ok=True)
