from ..contracts.task_intent import TaskIntent
from .scene_grounder import SceneGrounder


class SceneObjectSelector:
    """Scene edits use robot grounding, including relation and dialogue rules."""

    def __init__(self, *, category_aliases=None):
        self.category_aliases = category_aliases

    def resolve(self, target, entities, relations, scene, dialogue=None, bindings_override=None):
        needed = {target}
        while True:
            refs = {rel.reference for rel in relations
                    if rel.scope == "selection" and rel.subject in needed and rel.reference}
            if refs <= needed:
                break
            needed.update(refs)
        intent = TaskIntent(
            instruction="scene object selection",
            entities=[e for e in entities if e.entity_id in needed], operations=[],
            spatial_relations=[r for r in relations if r.scope == "selection" and r.subject in needed],
        )
        local = {key: value for key, value in (bindings_override or {}).items() if key in needed}
        dialogue_intent = intent.model_copy(update={"entities": [e for e in intent.entities if e.entity_id not in local]})
        overrides = dialogue.bindings(dialogue_intent, scene) if dialogue else {}
        overrides.update(local)
        task = SceneGrounder(category_aliases=self.category_aliases).ground(intent, scene, overrides)
        ids = next(e.scene_object_ids for e in task.entities if e.entity_id == target)
        by_id = {obj.scene_object_id: obj for obj in scene.objects}
        return [by_id[object_id] for object_id in ids]
