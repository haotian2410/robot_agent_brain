import re
from pydantic import BaseModel, ConfigDict, Field

class DialogueState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last_entity_id: str | None = None
    last_entity_ids: list[str] = Field(default_factory=list)

    def contextualize(self, instruction, scene):
        by_id = {o.scene_object_id: o for o in scene.objects}
        ids = self.last_entity_ids or ([self.last_entity_id] if self.last_entity_id else [])
        if not re.search(r"它们|这些|那些|它|刚才那个", instruction):
            return instruction
        if not ids or any(i not in by_id for i in ids):
            raise ValueError("dialogue_reference_missing")
        plural = bool(re.search(r"它们|这些|那些", instruction))
        if not plural and len(ids) != 1:
            raise ValueError("dialogue_reference_ambiguous")
        marker = "dialogue_ref_set" if plural else "dialogue_ref"
        return instruction + f" [{marker}={by_id[ids[0]].semantic_name}]"

    def bindings(self, intent, scene):
        known = {o.scene_object_id for o in scene.objects}
        result = {}
        for entity in intent.entities:
            if entity.dialogue_ref_set:
                ids = self.last_entity_ids
            elif entity.dialogue_ref:
                ids = [self.last_entity_id] if self.last_entity_id else []
            else:
                continue
            if not ids or any(i not in known for i in ids):
                raise ValueError("dialogue_reference_missing")
            if entity.dialogue_ref_set and not entity.all_available and entity.count != len(ids):
                raise ValueError("dialogue_reference_count_mismatch")
            result[entity.entity_id] = list(ids)
        return result

    def observe(self, result):
        if result.grounded_task is None:
            return
        by_id = {e.entity_id: e for e in result.grounded_task.entities}
        ids = list(dict.fromkeys(by_id[op.source or op.target].scene_object_id
                                 for op in result.grounded_task.operations))
        if ids:
            self.last_entity_ids = ids
            self.last_entity_id = ids[0] if len(ids) == 1 else None
