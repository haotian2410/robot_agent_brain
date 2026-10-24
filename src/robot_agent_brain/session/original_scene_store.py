"""Write-once original scene with a hash-checked manifest (caller holds session lock)."""
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig, SceneId, parse_scene_document
from ..contracts.robot_setup import RobotSetup
from ..adapters.scene_file_codec import SceneFileCodec
from ..filelock import sync_directory


class OriginalSceneManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    scene_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_request_id: str
    source: str
    task_object_ids: list[SceneId]
    platform_object_ids: list[SceneId]
    robot_setup: RobotSetup | None = None
    profile_object_map: dict[str, SceneId] | None = None
    config_fingerprint: str | None = None


class PreparedOriginalScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1.0"] = "1.0"
    scene_json: str
    manifest_json: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OriginalSceneStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def load(self, expected=None):
        try:
            self._recover_prepared(expected)
            paths = [self.directory / name for name in ("original_scene.json", "original_scene_manifest.json")]
            if any(p.is_symlink() for p in paths):
                raise ValueError("snapshot_symlink")
            scene_bytes = paths[0].read_bytes()
            manifest = OriginalSceneManifest.model_validate_json(paths[1].read_bytes())
            if hashlib.sha256(scene_bytes).hexdigest() != manifest.scene_sha256:
                raise ValueError("snapshot_hash_mismatch")
            if expected is not None and manifest != expected:
                raise ValueError("snapshot_manifest_mismatch")
            scene = parse_scene_document(json.loads(scene_bytes), uint32=False).view
            ids = {o.object_id_in_scene for o in scene.objects}
            tasks, platform = set(manifest.task_object_ids), set(manifest.platform_object_ids)
            if tasks & platform or tasks | platform != ids:
                raise ValueError("snapshot_manifest_objects_invalid")
            return scene, manifest
        except (OSError, ValueError) as exc:
            raise ValueError("original_scene_unavailable: " + str(exc)) from exc

    def _recover_prepared(self, expected=None):
        journal = self.directory / "original_scene_prepare.json"
        paths = [self.directory / name for name in ("original_scene.json", "original_scene_manifest.json")]
        marker = self.directory / "original_scene_commit.json"
        if any(p.is_symlink() for p in [journal, marker, *paths]):
            raise ValueError("snapshot_symlink")
        if not journal.exists():
            if any(p.exists() for p in paths) and not all(p.exists() for p in paths):
                raise ValueError("original_scene_recovery_required: no durable prepare record")
            if marker.exists():
                raise ValueError("original_scene_recovery_required: missing prepare record")
            return  # Legacy complete pairs remain readable, not re-frozen.
        prepared = PreparedOriginalScene.model_validate_json(journal.read_bytes())
        scene_bytes, manifest_bytes = prepared.scene_json.encode(), prepared.manifest_json.encode()
        manifest = OriginalSceneManifest.model_validate_json(manifest_bytes)
        if (hashlib.sha256(scene_bytes).hexdigest() != manifest.scene_sha256
                or hashlib.sha256(manifest_bytes).hexdigest() != prepared.manifest_sha256):
            raise ValueError("snapshot_prepare_hash_mismatch")
        if expected is not None and manifest != expected:
            raise ValueError("snapshot_manifest_mismatch")
        scene = parse_scene_document(json.loads(scene_bytes), uint32=False).view
        ids = {o.object_id_in_scene for o in scene.objects}
        tasks, platform = set(manifest.task_object_ids), set(manifest.platform_object_ids)
        if tasks & platform or tasks | platform != ids:
            raise ValueError("snapshot_manifest_objects_invalid")
        marker_bytes = json.dumps({"snapshot_id": manifest.snapshot_id, "scene_sha256": manifest.scene_sha256,
                                  "manifest_sha256": prepared.manifest_sha256}, sort_keys=True).encode()
        outputs = [*zip(paths, (scene_bytes, manifest_bytes)), (marker, marker_bytes)]
        # Validate every existing part before publishing anything missing.
        for path, payload in outputs:
            if path.exists() and path.read_bytes() != payload:
                raise ValueError("snapshot_prepare_existing_content_mismatch")
        for path, payload in outputs:
            if not path.exists():
                self._write_once(path, payload)

    def capture_once(self, scene, *, platform_object_ids, request_id, source, robot_setup=None, config_fingerprint=None, profile_object_map=None, allow_empty=False):
        paths = [self.directory / name for name in ("original_scene.json", "original_scene_manifest.json")]
        recovery_paths = [*paths, self.directory / "original_scene_prepare.json", self.directory / "original_scene_commit.json"]
        if any(p.exists() or p.is_symlink() for p in recovery_paths):
            # A partial write is an explicit recovery case, never permission to
            # overwrite the first scene with the newest scene.
            return self.load()[1]
        if platform_object_ids is None:
            return None
        ids = {o.object_id_in_scene for o in scene.objects}
        if not set(platform_object_ids) <= ids:
            raise ValueError("original_scene_platform_manifest_invalid")
        task_ids = ids - set(platform_object_ids)
        if not task_ids and not allow_empty:
            return None
        payload = json.dumps(SceneFileCodec.payload(scene), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        manifest = OriginalSceneManifest(snapshot_id=uuid.uuid4().hex, scene_sha256=hashlib.sha256(payload).hexdigest(),
            source_request_id=request_id, source=source, task_object_ids=sorted(task_ids),
            platform_object_ids=sorted(platform_object_ids), robot_setup=robot_setup, config_fingerprint=config_fingerprint,
            profile_object_map={str(k): v for k, v in profile_object_map.items()} if profile_object_map is not None else None)
        self.directory.mkdir(parents=True, exist_ok=True)
        manifest_json = manifest.model_dump_json(indent=2)
        prepared = PreparedOriginalScene(scene_json=payload.decode(), manifest_json=manifest_json,
            manifest_sha256=hashlib.sha256(manifest_json.encode()).hexdigest())
        self._write_once(self.directory / "original_scene_prepare.json", prepared.model_dump_json().encode())
        self._recover_prepared(manifest)
        return self.load(manifest)[1]

    @staticmethod
    def _write_once(path, payload):
        fd, temp = tempfile.mkstemp(prefix=".original-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            OriginalSceneStore._publish(temp, path)
            sync_directory(path.parent)
        finally:
            Path(temp).unlink(missing_ok=True)

    @staticmethod
    def _publish(temp, path):
        # A hard link is the atomic no-replace publish, including over an existing symlink.
        # exFAT has no hard links at all, so fall back to a rename; the caller holds the session
        # lock, and the target check keeps a pre-existing snapshot from being overwritten.
        try:
            os.link(temp, path)
        except OSError as exc:
            if path.is_symlink() or path.exists():
                raise ValueError("snapshot_write_once_target_exists") from exc
            os.replace(temp, path)
