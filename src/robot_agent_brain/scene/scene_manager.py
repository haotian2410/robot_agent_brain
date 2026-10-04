from __future__ import annotations

from ..contracts.scene import PatchAction, SceneConfig, ScenePatch


class SceneManager:
    def __init__(self, scene: SceneConfig):
        self.scene = scene.model_copy(deep=True)

    def apply_patch(self, patch: ScenePatch) -> SceneConfig:
        if patch.scene_id != self.scene.scene_id:
            raise ValueError("scene_patch_scene_mismatch")
        if patch.base_scene_version != self.scene.scene_version:
            raise ValueError("scene_patch_version_conflict")
        objects = {item.scene_object_id: item.model_copy(deep=True) for item in self.scene.objects}
        for operation in patch.operations:
            object_id = operation.scene_object_id
            if operation.action == PatchAction.ADD:
                if object_id in objects:
                    raise ValueError(f"scene_object_already_exists: {object_id}")
                objects[object_id] = operation.object.model_copy(deep=True)
            elif operation.action == PatchAction.REMOVE:
                if object_id not in objects:
                    raise ValueError(f"scene_object_missing: {object_id}")
                del objects[object_id]
            elif operation.action == PatchAction.UPDATE_TRANSFORM:
                if object_id not in objects:
                    raise ValueError(f"scene_object_missing: {object_id}")
                objects[object_id] = objects[object_id].model_copy(update={"transform": operation.transform})
            elif operation.action == PatchAction.UPDATE_PROPERTY:
                if object_id not in objects:
                    raise ValueError(f"scene_object_missing: {object_id}")
                merged = {**objects[object_id].properties, **operation.properties}
                objects[object_id] = objects[object_id].model_copy(update={"properties": merged})
        self.scene = self.scene.model_copy(update={
            "scene_version": self.scene.scene_version + 1,
            "objects": list(objects.values()),
        })
        return self.scene.model_copy(deep=True)

