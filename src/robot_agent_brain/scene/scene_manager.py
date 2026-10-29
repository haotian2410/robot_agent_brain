"""Atomic component patches; historical identity belongs to the Session."""
from ..contracts.scene import PatchAction, SceneConfig, ScenePatch, SceneComponent, parse_scene_document


class SceneManager:
    def __init__(self, scene, *, seen_scene_object_ids=None, next_scene_object_id=None):
        source = scene.raw_document() if hasattr(scene, "raw_document") else scene.model_dump(mode="json")
        # A caller may have edited the typed view in memory before creating a
        # manager (legacy/local platform tests do this).  Keep the lossless
        # top-level document, but take the current object list as the source
        # of truth so those edits are not silently discarded.
        if hasattr(scene, "model_dump"):
            source = dict(source)
            source["objects"] = scene.model_dump(mode="json").get("objects", [])
        document = parse_scene_document(source, uint32=False)
        if document.rejected_objects:
            reasons = ",".join(sorted({str(item.get("reason", "unknown")) for item in document.rejected_objects}))
            raise ValueError("scene_object_rejected:" + reasons)
        self.scene = document.view
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
        raw_objects = {
            item.get("object_id_in_scene"): item
            for item in self.scene.raw_document().get("objects", [])
            if isinstance(item, dict) and isinstance(item.get("object_id_in_scene"), int)
        }
        changed = set()
        seen = set(self.seen_scene_object_ids)
        for operation in patch.operations:
            identifier = operation.object_id_in_scene
            if operation.action == PatchAction.ADD:
                if identifier in seen:
                    raise ValueError(f"scene_object_id_reused: {identifier}")
                objects[identifier] = operation.object.model_copy(deep=True)
                seen.add(identifier)
                changed.add(identifier)
                continue
            if identifier not in objects:
                raise ValueError(f"scene_object_missing: {identifier}")
            if operation.action == PatchAction.REMOVE:
                # Do not leave dangling parent/support references.  A remove
                # patch is atomic, so reject it before deleting the parent
                # rather than producing a scene that only fails on the next
                # parse/round-trip.
                for child in objects.values():
                    if child.object_id_in_scene == identifier:
                        continue
                    child_transform = next((c for c in child.components
                                            if c.component_type == "Transform"), None)
                    if child_transform is not None and child_transform.properties.get("parent") == identifier:
                        raise ValueError("parent_invalid")
                    semantic = next((c for c in child.components
                                     if c.component_type == "Semantic"), None)
                    if semantic is not None and semantic.properties.get("support") == identifier:
                        raise ValueError("parent_invalid")
                del objects[identifier]
                changed.add(identifier)
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
            changed.add(identifier)
        payload = self.scene.raw_document()
        payload.update({"objects": [
            (objects[identifier].model_dump(mode="json") if identifier in changed
             else raw_objects.get(identifier, objects[identifier].model_dump(mode="json")))
            for identifier in objects
        ],
                        "scene_version": self.scene.scene_version + 1})
        # §1.2: a scene_version bump resets the sub-version, and a document writes that zero as an
        # absent key -- the browser drops it in toJSON().  Materialising "scene_sub_version": 0 here
        # would make the committed digest disagree with the world read back after the commit.
        payload.pop("scene_sub_version", None)
        document = parse_scene_document(payload, uint32=False)
        if document.rejected_objects:
            reasons = ",".join(sorted({str(item.get("reason", "unknown")) for item in document.rejected_objects}))
            raise ValueError("scene_object_rejected:" + reasons)
        candidate = document.view
        self.scene = candidate
        self.seen_scene_object_ids = seen
        self.next_scene_object_id = max(self.next_scene_object_id, max(seen, default=-1) + 1)
        return candidate.model_copy(deep=True)
