"""Atomic component patches; historical identity belongs to the Session."""
from ..contracts.scene import PatchAction, SceneConfig, ScenePatch, SceneComponent


class SceneManager:
    def __init__(self, scene, *, seen_scene_object_ids=None, next_scene_object_id=None):
        self.scene = SceneConfig.model_validate(scene.model_dump())
        current = {o.object_id_in_scene for o in self.scene.objects}
        history = set(seen_scene_object_ids or ())
        if any(type(value) is not int or not 0 <= value < 2**53 for value in history):
            raise ValueError("scene_identity_history_invalid")
        if next_scene_object_id is not None and (
                type(next_scene_object_id) is not int or not 0 <= next_scene_object_id <= 2**53):
            raise ValueError("scene_next_object_id_invalid")
        self.seen_scene_object_ids = history | current
        self.next_scene_object_id = max(max(self.seen_scene_object_ids, default=-1) + 1,
                                        next_scene_object_id if next_scene_object_id is not None else 0)

    def apply_patch(self, patch):
        patch = ScenePatch.model_validate(patch.model_dump())
        if patch.scene_id != self.scene.scene_id:
            raise ValueError("scene_patch_scene_mismatch")
        if patch.base_scene_version != self.scene.scene_version:
            raise ValueError("scene_patch_version_conflict")
        objects = {o.object_id_in_scene: o.model_copy(deep=True) for o in self.scene.objects}
        seen = set(self.seen_scene_object_ids)
        for operation in patch.operations:
            identifier = operation.object_id_in_scene
            if operation.action == PatchAction.ADD:
                if identifier in seen:
                    raise ValueError(f"scene_object_id_reused: {identifier}")
                objects[identifier] = operation.object.model_copy(deep=True)
                seen.add(identifier)
                continue
            if identifier not in objects:
                raise ValueError(f"scene_object_missing: {identifier}")
            if operation.action == PatchAction.REMOVE:
                del objects[identifier]
                continue
            current = objects[identifier]
            kind = operation.component.component_type if operation.component else operation.component_type
            components = list(current.components)
            matching = next((i for i, c in enumerate(components) if c.component_type == kind), None)
            if operation.action == PatchAction.REMOVE_COMPONENT:
                if matching is None:
                    raise ValueError("scene_component_missing: " + kind)
                components.pop(matching)
            else:
                component = operation.component.model_copy(deep=True)
                if matching is None:
                    components.append(component)
                else:
                    components[matching] = component
                changed_transform = (kind == "Transform" and
                    (matching is None or current.components[matching].properties != component.properties))
                if changed_transform:
                    components = [SceneComponent(component_type="Semantic", properties={**c.properties, "support": None})
                                  if c.component_type == "Semantic" else c for c in components]
            objects[identifier] = current.model_copy(update={"components": components})
        candidate = SceneConfig.model_validate({**self.scene.model_dump(), "objects": list(objects.values()),
                                                "scene_version": self.scene.scene_version + 1})
        self.scene = candidate
        self.seen_scene_object_ids = seen
        self.next_scene_object_id = max(self.next_scene_object_id, max(seen, default=-1) + 1)
        return candidate.model_copy(deep=True)
