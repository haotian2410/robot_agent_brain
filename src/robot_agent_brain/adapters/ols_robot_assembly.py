"""OLS-backed robot/attachment/camera assembly information.

This module deliberately contains no planning or execution policy.  It reads
the same metadata that WebEditor uses to assemble a platform, but keeps the
result as Brain-owned, immutable data.  A RobotProfile is still required for
planning; an OLS entry alone only proves that a scene can be assembled and
displayed.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from ..contracts.scene import SceneConfig, SceneComponent, SceneObject
from ..scene.component_access import SceneIndex
from ..scene.scene_graph import world_transform


@dataclass(frozen=True)
class RobotAssemblyAsset:
    asset_key: str
    semantic_name: str
    asset_type: str
    role: str
    metadata_ref: str
    tags: tuple[str, ...] = ()
    connect_joints: tuple[str, ...] = ()
    connect_links: tuple[str, ...] = ()
    child_link: str | None = None
    driver: dict | None = None
    scene_one_arm: dict | None = None
    aabb: tuple[float, ...] | None = None


class OlsRobotAssemblyAdapter:
    """Read OLS assembly metadata and build an atomic platform candidate."""

    def __init__(self, assets):
        self.assets = assets
        self.root = Path(getattr(assets, "root", "")).resolve() if getattr(assets, "root", None) else None
        self.revision = self._revision()
        self._items: dict[str, RobotAssemblyAsset] = {}
        self._load()

    def _revision(self) -> str:
        if self.root is None or not self.root.exists():
            return "unknown"
        version = (self.root / "VERSION.txt").read_text(encoding="utf-8").strip() if (self.root / "VERSION.txt").is_file() else "unknown"
        digest = hashlib.sha256()
        for path in sorted(self.root.glob("robots/*/*.json")):
            digest.update(path.relative_to(self.root).as_posix().encode())
            digest.update(path.read_bytes())
        return f"{version}:{digest.hexdigest()}"

    @staticmethod
    def _list(value):
        return tuple(item for item in (value or []) if isinstance(item, str) and item)

    def _load(self):
        if self.root is None:
            return
        index_path = self.root / "robots" / "robot_index.json"
        if not index_path.is_file():
            return
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for raw_id, name in (index.get("by_id") or {}).items():
            identifier = int(raw_id)
            path = self.root / "robots" / str(identifier) / f"{name}.json"
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            semantic = data.get("semantic_properties") or {}
            tag = str(semantic.get("tag") or "")
            tags = tuple(part.strip().casefold() for part in tag.split(",") if part.strip())
            driver = (data.get("robot_driver") or {}).get("properties")
            driver = dict(driver) if isinstance(driver, dict) else None
            attachment = (driver or {}).get("robot_attachment") or {}
            attachment = attachment.get("properties") if isinstance(attachment, dict) else {}
            child = self._list((attachment or {}).get("child_link"))
            joints = self._list((driver or {}).get("available_connect_joints"))
            links = self._list((driver or {}).get("available_connect_link"))
            if joints or links:
                role = "arm"
            elif child:
                role = "gripper"
            elif any("camera" in tag for tag in tags) or "camera" in name.casefold():
                role = "camera"
            else:
                role = "prop"
            aabb = data.get("geometric_properties", {}).get("AABB")
            self._items[f"robot:{identifier}"] = RobotAssemblyAsset(
                asset_key=f"robot:{identifier}", semantic_name=str(name), asset_type="robot",
                role=role, metadata_ref=f"$LIBRARY_SERVER/{identifier}", tags=tags,
                connect_joints=joints, connect_links=links,
                child_link=child[0] if child else None, driver=driver,
                scene_one_arm=(data.get("scene_one_arm") or [None])[0],
                aabb=tuple(float(v) for v in aabb) if isinstance(aabb, list) and len(aabb) == 6 else None)

    def catalog(self, registered_profiles=()) -> list[dict]:
        profiles = {str(value).casefold() for value in (registered_profiles or ())}
        return [{"asset_key": item.asset_key, "semantic_name": item.semantic_name,
                 "role": item.role, "tags": list(item.tags),
                 "connect_joints": list(item.connect_joints),
                 "connect_links": list(item.connect_links), "child_link": item.child_link,
                 "profile_registered": item.semantic_name.casefold() in profiles
                 or (item.semantic_name == "ur5e_arm" and "ur5e" in profiles)}
                for item in sorted(self._items.values(), key=lambda value: value.asset_key)]

    def resolve(self, name: str, *, role: str | None = None) -> RobotAssemblyAsset:
        raw = str(name or "").strip().casefold()
        matches = [item for item in self._items.values()
                   if item.semantic_name.casefold() == raw or item.asset_key.casefold() == raw]
        if role is not None:
            matches = [item for item in matches if item.role == role]
        if len(matches) != 1:
            if not matches:
                raise ValueError("robot_asset_unknown:" + str(name))
            raise ValueError("robot_asset_ambiguous:" + str(name))
        return matches[0]

    def classify_scene(self, scene: SceneConfig) -> dict[str, list[tuple[int, RobotAssemblyAsset]]]:
        result = {"arm": [], "gripper": [], "camera": [], "prop": []}
        index = SceneIndex(scene)
        for obj in scene.objects:
            ref = index.metadata_ref(obj.object_id_in_scene)
            if not ref or index.metadata_type(obj.object_id_in_scene) != "robot":
                continue
            key = "robot:" + ref.rsplit("/", 1)[-1]
            asset = self._items.get(key)
            if asset is None:
                continue
            if index.component(obj.object_id_in_scene, "Camera") is not None and asset.role == "camera":
                result["camera"].append((obj.object_id_in_scene, asset))
            else:
                result.setdefault(asset.role, []).append((obj.object_id_in_scene, asset))
        return result

    def scene_binding(self, scene: SceneConfig) -> dict:
        classified = self.classify_scene(scene)
        camera_names = {item.semantic_name for _, item in classified["camera"]}
        return {"robot_asset": classified["arm"][0][1].semantic_name if len(classified["arm"]) == 1 else None,
                "gripper_asset": classified["gripper"][0][1].semantic_name if len(classified["gripper"]) == 1 else None,
                # Templates commonly contain two identical RGB cameras.  The
                # asset binding is still unambiguous when every camera uses
                # the same OLS metadata; camera_id selection remains separate.
                "camera_asset": next(iter(camera_names)) if len(camera_names) == 1 else None}

    def platform_object_ids(self, scene: SceneConfig, previous=None) -> set[int]:
        """Return the platform ids that survive an assembly replacement.

        Lights and the primary support surface are retained from ``previous``;
        robot-space objects are re-derived from the candidate so a pedestal can
        be added or removed without leaving a stale manifest entry.
        """
        ids = set(previous or ()) & {obj.object_id_in_scene for obj in scene.objects}
        classified = self.classify_scene(scene)
        for role in ("arm", "gripper", "camera"):
            ids.update(identifier for identifier, _ in classified[role])
        index = SceneIndex(scene)
        for obj in scene.objects:
            if index.metadata_type(obj.object_id_in_scene) != "robot":
                continue
            semantic = index.semantic(obj.object_id_in_scene)
            if semantic and semantic.category in {"support", "pedestal", "robot_support"}:
                ids.add(obj.object_id_in_scene)
        return ids

    @staticmethod
    def _corners(minimum, maximum):
        return [(x, y, z) for x in (minimum[0], maximum[0])
                for y in (minimum[1], maximum[1])
                for z in (minimum[2], maximum[2])]

    @staticmethod
    def _world_aabb(scene, object_id, asset):
        transform = world_transform(scene, object_id)
        points = [transform.point(corner) for corner in
                  OlsRobotAssemblyAdapter._corners(asset.local_aabb_min_m, asset.local_aabb_max_m)]
        return tuple(min(point[axis] for point in points) for axis in range(3)), \
            tuple(max(point[axis] for point in points) for axis in range(3))

    def _table_box(self, scene):
        index = SceneIndex(scene)
        for obj in scene.objects:
            identifier = obj.object_id_in_scene
            if index.metadata_type(identifier) != "model":
                continue
            ref = index.metadata_ref(identifier)
            try:
                asset = self.assets.resolve(ref, asset_type="model")
            except Exception:
                continue
            if asset.semantic_name in {"table", "coffee_table"}:
                return identifier, self._world_aabb(scene, identifier, asset)
        return None, None

    @staticmethod
    def _arm_pose(table_box, percent, side):
        minimum, maximum = table_box
        edge = tuple(maximum[i] - minimum[i] for i in range(3))
        center = tuple((minimum[i] + maximum[i]) / 2 for i in range(3))
        return [center[0] + side * percent[0] * edge[0],
                minimum[1] + percent[1] * edge[1],
                maximum[2] + percent[2] * edge[2]], [0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)]

    @staticmethod
    def _placement(asset):
        value = asset.scene_one_arm or {}
        percent = value.get("robot_pose_percent_compared_to_table_length_center")
        if not isinstance(percent, list) or len(percent) != 3:
            percent = [0.2, 0.3, 0.5]
        return tuple(float(item) for item in percent), bool(value.get("has_pedestal", False)), value.get("pedestal_id"), value.get("pedestal_scale") or [1.0, 1.0, 1.0]

    @staticmethod
    def _scene_driver(value: dict | None) -> dict:
        """Drop OLS-only placement fields before writing Scene RobotDriver."""
        allowed = {"joint_sequence", "joint_limits", "initial_joint_positions_rad",
                    "now_joint_positions_rad", "available_connect_joints", "role"}
        return {key: item for key, item in (value or {}).items() if key in allowed}

    @staticmethod
    def _replace(obj: SceneObject, *, metadata=None, driver=None, attachment=None, semantic=None, transform=None) -> SceneObject:
        values = {component.component_type: component.model_dump(mode="json") for component in obj.components}
        for name, properties in (("MetadataRef", metadata), ("RobotDriver", driver),
                                 ("RobotAttachment", attachment), ("Semantic", semantic),
                                 ("Transform", transform)):
            if properties is None:
                continue
            values[name] = {"component_type": name, "properties": properties}
        return obj.model_copy(update={"components": [SceneComponent.model_validate(values[key])
                                                       for key in values]})

    def rebind_scene(self, scene: SceneConfig, *, robot_asset: str | None = None,
                     gripper_asset: str | None = None, camera_asset: str | None = None,
                     next_object_id: int | None = None) -> tuple[SceneConfig, dict]:
        """Build a candidate without touching ``scene`` or assigning a version."""
        current = self.classify_scene(scene)
        arms = current["arm"]
        if len(arms) != 1:
            raise ValueError("robot_assembly_arm_ambiguous")
        arm_id, old_arm = arms[0]
        arm_changed = robot_asset is not None
        target_arm = self.resolve(robot_asset, role="arm") if arm_changed else old_arm
        target_gripper = self.resolve(gripper_asset, role="gripper") if gripper_asset else None
        target_camera = self.resolve(camera_asset, role="camera") if camera_asset else None
        objects = {obj.object_id_in_scene: obj.model_copy(deep=True) for obj in scene.objects}
        table_id, table_box = self._table_box(scene)
        percent, has_pedestal, pedestal_id, pedestal_scale = self._placement(target_arm)
        if arm_changed and table_box is not None and target_arm.aabb is not None:
            for arm_index, (identifier, _) in enumerate(arms):
                position, quaternion = self._arm_pose(table_box, percent, 1 if arm_index % 2 == 0 else -1)
                old_transform = SceneIndex(scene).transform(identifier)
                arm_obj = objects[identifier]
                arm_obj = self._replace(arm_obj,
                    transform={"position": position, "quaternion_xyzw": quaternion,
                               "scale": list(old_transform.scale), "parent": old_transform.parent})
                objects[identifier] = arm_obj
        driver = self._scene_driver(target_arm.driver)
        for identifier, _ in arms:
            arm_obj = objects[identifier]
            old_semantic = SceneIndex(scene).semantic(identifier)
            arm_obj = self._replace(arm_obj,
                metadata={"path": target_arm.metadata_ref, "type": "robot"},
                driver=driver,
                semantic={**(old_semantic.model_dump(mode="json") if old_semantic else {}),
                          "semantic_name": target_arm.semantic_name, "category": "robot"})
            objects[identifier] = arm_obj
        if target_gripper:
            grippers = current["gripper"]
            if len(grippers) > 1:
                raise ValueError("robot_assembly_gripper_ambiguous")
            gid = grippers[0][0] if grippers else (max(objects, default=-1) + 1 if next_object_id is None else next_object_id)
            if gid in objects and gid not in {item[0] for item in grippers}:
                raise ValueError("robot_assembly_object_id_collision")
            parent_joint = target_arm.connect_joints[0] if target_arm.connect_joints else ""
            parent_link = target_arm.connect_links[0] if target_arm.connect_links else ""
            driver = self._scene_driver(target_gripper.driver)
            mount_position = (target_gripper.driver or {}).get("position") or [[0.0, 0.0, 0.0]]
            mount_quaternion = (target_gripper.driver or {}).get("quaternion_xyzw") or [[0.0, 0.0, 0.0, 1.0]]
            position = list(mount_position[0]) if mount_position and isinstance(mount_position[0], list) else [0.0, 0.0, 0.0]
            quaternion = list(mount_quaternion[0]) if mount_quaternion and isinstance(mount_quaternion[0], list) else [0.0, 0.0, 0.0, 1.0]
            gripper_obj = objects[gid] if gid in objects else SceneObject.model_validate({
                "object_id_in_scene": gid, "object_name_in_scene": target_gripper.semantic_name,
                "components": [{"component_type": "Transform", "properties": {"parent": arm_id}},
                                {"component_type": "MetadataRef", "properties": {"path": target_gripper.metadata_ref, "type": "robot"}},
                                {"component_type": "RobotDriver", "properties": driver},
                                {"component_type": "RobotAttachment", "properties": {"parent_object_id": arm_id,
                                    "parent_joint": parent_joint, "parent_link": parent_link, "child_link": target_gripper.child_link or "",
                                    "connection_type": "fixed", "transform": {"position": position, "quaternion_xyzw": quaternion,
                                                                                  "reference_frame": "parent_link"}}},
                                {"component_type": "Semantic", "properties": {"semantic_name": target_gripper.semantic_name,
                                                                                  "category": "end_effector", "support": None}}]})
            gripper_obj = self._replace(gripper_obj,
                metadata={"path": target_gripper.metadata_ref, "type": "robot"}, driver=driver,
                attachment={"parent_object_id": arm_id, "parent_joint": parent_joint,
                            "parent_link": parent_link, "child_link": target_gripper.child_link or "",
                            "connection_type": "fixed", "transform": {"position": position,
                                                                           "quaternion_xyzw": quaternion,
                                                                           "reference_frame": "parent_link"}},
                semantic={"semantic_name": target_gripper.semantic_name, "category": "end_effector", "support": None},
                transform={"position": list(SceneIndex(scene).transform(gid).position or (0, 0, 0)) if gid in objects else [0, 0, 0],
                           "quaternion_xyzw": list(SceneIndex(scene).transform(gid).quaternion_xyzw or (0, 0, 0, 1)) if gid in objects else [0, 0, 0, 1],
                           "scale": list(SceneIndex(scene).transform(gid).scale) if gid in objects else [1, 1, 1], "parent": arm_id})
            objects[gid] = gripper_obj
        # Match the browser's OLS placement behavior for the support pedestal:
        # keep its object id when replacing, add it when required, and remove
        # old pedestal objects when the target arm has no pedestal.
        index = SceneIndex(scene)
        pedestal_ids = []
        for identifier in list(objects):
            if index.metadata_type(identifier) != "robot":
                continue
            semantic = index.semantic(identifier)
            if semantic and semantic.category in {"support", "pedestal", "robot_support"}:
                pedestal_ids.append(identifier)
        target_pedestal = self._items.get(f"robot:{int(pedestal_id)}") if pedestal_id is not None else None
        if (arm_changed and has_pedestal and target_pedestal is not None
                and table_box is not None and target_arm.aabb is not None):
            arm_pose, _ = self._arm_pose(table_box, percent, 1)
            arm_bottom = arm_pose[2] + min(target_arm.aabb[4], target_arm.aabb[5])
            pedestal_asset = self.assets.resolve(target_pedestal.metadata_ref, asset_type="robot")
            pedestal_id_in_scene = pedestal_ids[0] if pedestal_ids else (max(objects, default=-1) + 1)
            pedestal_z = arm_bottom - pedestal_asset.local_aabb_max_m[2] * float(pedestal_scale[2])
            pedestal_values = {"position": [arm_pose[0], arm_pose[1], pedestal_z],
                               "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
                               "scale": list(pedestal_scale), "parent": None}
            if pedestal_id_in_scene in objects:
                objects[pedestal_id_in_scene] = self._replace(objects[pedestal_id_in_scene],
                    metadata={"path": target_pedestal.metadata_ref, "type": "robot"},
                    semantic={"semantic_name": target_pedestal.semantic_name, "category": "support", "support": None},
                    transform=pedestal_values)
            else:
                objects[pedestal_id_in_scene] = SceneObject.model_validate({
                    "object_id_in_scene": pedestal_id_in_scene,
                    "object_name_in_scene": target_pedestal.semantic_name,
                    "components": [{"component_type": "Transform", "properties": pedestal_values},
                                    {"component_type": "MetadataRef", "properties": {"path": target_pedestal.metadata_ref, "type": "robot"}},
                                    {"component_type": "Semantic", "properties": {"semantic_name": target_pedestal.semantic_name, "category": "support", "support": None}}]})
            for identifier in pedestal_ids:
                if identifier != pedestal_id_in_scene:
                    objects.pop(identifier, None)
        elif arm_changed:
            for identifier in pedestal_ids:
                objects.pop(identifier, None)
        if target_camera:
            cameras = current["camera"]
            if not cameras:
                raise ValueError("robot_assembly_camera_ambiguous")
            for cid, _ in cameras:
                objects[cid] = self._replace(objects[cid], metadata={"path": target_camera.metadata_ref, "type": "robot"})
        payload = scene.raw_document()
        payload["objects"] = [obj.model_dump(mode="json") for obj in objects.values()]
        payload["scene_sub_version"] = scene.scene_sub_version + 1
        payload.pop("scene_version", None)
        payload["scene_version"] = scene.scene_version
        candidate = SceneConfig.model_validate(payload)
        return candidate, {"robot_asset": target_arm.semantic_name,
                           "gripper_asset": target_gripper.semantic_name if target_gripper else (current["gripper"][0][1].semantic_name if current["gripper"] else None),
                           "camera_asset": target_camera.semantic_name if target_camera else (current["camera"][0][1].semantic_name if current["camera"] else None),
                           "asset_revision": self.revision}
