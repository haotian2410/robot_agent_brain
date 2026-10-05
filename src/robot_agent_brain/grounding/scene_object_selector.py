from ..contracts.task_intent import TaskIntent
from .scene_grounder import SceneGrounder


class SceneObjectSelector:
    """Scene edits use robot grounding, including relation and dialogue rules."""

    def resolve(self, target, entities, relations, scene, dialogue=None):
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
        overrides = dialogue.bindings(intent, scene) if dialogue else {}
        task = SceneGrounder().ground(intent, scene, overrides)
        ids = next(e.scene_object_ids for e in task.entities if e.entity_id == target)
        by_id = {obj.scene_object_id: obj for obj in scene.objects}
        return [by_id[object_id] for object_id in ids]
