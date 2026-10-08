import re
from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneId
from ..scene.component_access import SceneIndex

class DialogueState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last_entity_id: SceneId | None = None
    last_entity_ids: list[SceneId] = Field(default_factory=list)

    def contextualize(self, instruction, scene):
        by_id = {o.object_id_in_scene: o for o in scene.objects}
        ids = self.last_entity_ids or ([self.last_entity_id] if self.last_entity_id is not None else [])
        plural = bool(re.search(r"它们|这些|那些", instruction))
        if "另一个" in instruction:
            if self.last_entity_id is None or self.last_entity_id not in by_id:
                raise ValueError("dialogue_reference_missing")
            semantic = SceneIndex(scene).semantic(self.last_entity_id)
            if semantic is None:
                raise ValueError("dialogue_reference_missing")
            return instruction + f" [dialogue_exclude={semantic.semantic_name}]"
        if not re.search(r"它们|这些|那些|它|刚才那个", instruction):
            return instruction
        if not ids or any(i not in by_id for i in ids):
            # Demonstratives on the first turn may describe the visible
            # current scene; only a singular pronoun requires a prior binding.
            if plural:
                return instruction
            raise ValueError("dialogue_reference_missing")
        if not plural and len(ids) != 1:
            raise ValueError("dialogue_reference_ambiguous")
        marker = "dialogue_ref_set" if plural else "dialogue_ref"
        semantics = [SceneIndex(scene).semantic(i) for i in ids]
        if any(value is None for value in semantics):
            raise ValueError("dialogue_reference_missing")
        names = list(dict.fromkeys(value.semantic_name for value in semantics))
        return instruction + f" [{marker}={','.join(names)}]"

    def apply_exclusions(self, turn, scene, *, aliases=None):
        """Bind 'another' in Python; never ask the model for physical IDs."""
        if "另一个" not in turn.instruction or turn.status != "accepted":
            return turn
        if self.last_entity_id is None:
            raise ValueError("dialogue_reference_missing")
        semantic = SceneIndex(scene).semantic(self.last_entity_id)
        if semantic is None:
            raise ValueError("dialogue_reference_missing")
        field = {"robot_task": "task_intent", "scene_edit": "scene_edit",
                 "scene_query": "scene_query"}.get(turn.turn_kind)
        if field is None:
            return turn
        payload = getattr(turn, field)
        aliases = {key.casefold(): value.casefold() for key, value in (aliases or {}).items()}
        def canonical(name):
            return aliases.get(name.casefold(), name.casefold())
        candidates = [entity for entity in payload.entities
                      if canonical(semantic.semantic_name) in
                      {canonical(name) for name in [entity.semantic_name, *entity.aliases]}
                      or entity.category_only and entity.category == semantic.category]
        if len(candidates) != 1:
            raise ValueError("dialogue_reference_ambiguous")
        target = candidates[0]
        data = target.model_dump()
        data["exclude_scene_object_ids"] = list(dict.fromkeys(
            [*target.exclude_scene_object_ids, self.last_entity_id]))
        data["dialogue_ref"] = False
        data["dialogue_ref_set"] = False
        replacement = type(target).model_validate(data)
        entities = [replacement if entity.entity_id == target.entity_id else entity
                    for entity in payload.entities]
        return turn.model_copy(update={field: payload.model_copy(update={"entities": entities})})

    def bindings(self, intent, scene):
        known = {o.object_id_in_scene for o in scene.objects}
        result = {}
        for entity in intent.entities:
            if entity.dialogue_ref_set:
                ids = self.last_entity_ids
            elif entity.dialogue_ref:
                ids = [self.last_entity_id] if self.last_entity_id is not None else []
            else:
                continue
            if not ids or any(i not in known for i in ids):
                raise ValueError("dialogue_reference_missing")
            if entity.dialogue_ref_set and not entity.all_available and entity.count != len(ids):
                raise ValueError("dialogue_reference_count_mismatch")
            result[entity.entity_id] = list(ids)
        return result

    def observe(self, result):
        if result.status != "accepted":
            return
        deleted = set(result.deleted_object_ids)
        if deleted:
            ids = [i for i in (self.last_entity_ids or ([self.last_entity_id] if self.last_entity_id is not None else [])) if i not in deleted]
            self.last_entity_ids = ids
            self.last_entity_id = ids[0] if len(ids) == 1 else None
        if result.focus_object_ids is not None:
            ids = list(dict.fromkeys(i for i in result.focus_object_ids if i not in deleted))
            self.last_entity_ids = ids
            self.last_entity_id = ids[0] if len(ids) == 1 else None
            return
        if result.grounded_task is None:
            return
        by_id = {e.entity_id: e for e in result.grounded_task.entities}
        ids = list(dict.fromkeys(by_id[op.source or op.target].scene_object_id
                                 for op in result.grounded_task.operations))
        if ids:
            self.last_entity_ids = ids
            self.last_entity_id = ids[0] if len(ids) == 1 else None
