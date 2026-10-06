from __future__ import annotations

from ..contracts.scene import PatchAction, SceneConfig, ScenePatch


class SceneManager:
    def __init__(self, scene: SceneConfig):
        self.scene = SceneConfig.model_validate(scene.model_dump())

    def apply_patch(self, patch: ScenePatch) -> SceneConfig:
        patch = ScenePatch.model_validate(patch.model_dump())
        if patch.scene_id != self.scene.scene_id:
            raise ValueError("scene_patch_scene_mismatch")
        if patch.base_scene_version != self.scene.scene_version:
            raise ValueError("scene_patch_version_conflict")
        objects = {item.scene_object_id: item.model_copy(deep=True) for item in self.scene.objects}
        retired = list(self.scene.retired_object_ids)
        for operation in patch.operations:
            object_id = operation.scene_object_id
            if operation.action == PatchAction.ADD:
                if object_id in retired:
                    raise ValueError(f"scene_object_id_retired: {object_id}")
                if object_id in objects:
                    raise ValueError(f"scene_object_already_exists: {object_id}")
                objects[object_id] = operation.object.model_copy(deep=True)
            elif operation.action == PatchAction.REMOVE:
                if object_id not in objects:
                    raise ValueError(f"scene_object_missing: {object_id}")
                del objects[object_id]
                retired.append(object_id)
            elif operation.action == PatchAction.UPDATE_TRANSFORM:
                if object_id not in objects:
                    raise ValueError(f"scene_object_missing: {object_id}")
                current = objects[object_id]
                properties = dict(current.properties)
                # A direct transform edit invalidates derived containment/support
                # facts; they must be re-established by the next grounding pass.
                for key in ("container_membership", "support", "support_relation"):
                    properties.pop(key, None)
                objects[object_id] = current.model_copy(update={"transform": operation.transform, "properties": properties})
            elif operation.action == PatchAction.UPDATE_PROPERTY:
                if object_id not in objects:
                    raise ValueError(f"scene_object_missing: {object_id}")
                merged = {**objects[object_id].properties, **operation.properties}
                objects[object_id] = objects[object_id].model_copy(update={"properties": merged})
        values = self.scene.model_dump()
        values.update({
            "scene_version": self.scene.scene_version + 1,
            "objects": list(objects.values()),
            "retired_object_ids": list(dict.fromkeys(retired)),
        })
        candidate = SceneConfig.model_validate(values)
        self.scene = candidate
        return self.scene.model_copy(deep=True)
