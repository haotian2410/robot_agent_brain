from ..contracts.task_intent import TaskIntent
from ..contracts.spatial import ResolvedSelectionRelation
from .scene_grounder import SceneGrounder
from .scene_reference_resolver import SceneReferenceResolver
from .scene_relation_resolver import SceneRelationResolver


class SceneObjectSelector:
    """Scene edits use robot grounding, including relation and dialogue rules."""

    def __init__(self, *, aliases=None, category_aliases=None, assets=None,
                 scene_reference_catalog=None, table_metadata_ref=None):
        self.assets = assets
        self.aliases = aliases
        self.category_aliases = category_aliases
        self.reference_resolver = SceneReferenceResolver(scene_reference_catalog,
                                                         table_metadata_ref=table_metadata_ref)

    def resolve(self, target, entities, relations, scene, dialogue=None, bindings_override=None):
        entity_ids = {entity.entity_id for entity in entities}
        needed = {target}
        while True:
            refs = {rel.reference for rel in relations
                    if rel.scope == "selection" and rel.subject in needed and rel.reference
                    and rel.reference in entity_ids}
            if refs <= needed:
                break
            needed.update(refs)
        internal_relations = []
        external_relations = {}
        for relation in relations:
            if relation.scope != "selection" or relation.subject not in needed:
                continue
            if relation.reference and relation.reference not in entity_ids:
                resolved = self.reference_resolver.resolve(relation.reference, entities=entities, scene=scene)
                if resolved.object_id is None:
                    raise ValueError("scene_reference_unresolved: " + relation.reference)
                external_relations.setdefault(relation.subject, []).append(
                    ResolvedSelectionRelation(relation=relation.relation, reference_object_id=resolved.object_id))
            else:
                internal_relations.append(relation)
        intent = TaskIntent(
            instruction="scene object selection",
            entities=[e for e in entities if e.entity_id in needed], operations=[],
            spatial_relations=internal_relations,
        )
        local = {key: value for key, value in (bindings_override or {}).items() if key in needed}
        dialogue_intent = intent.model_copy(update={"entities": [e for e in intent.entities if e.entity_id not in local]})
        overrides = dialogue.bindings(dialogue_intent, scene) if dialogue else {}
        overrides.update(local)
        task = SceneGrounder(aliases=self.aliases, category_aliases=self.category_aliases, assets=self.assets).ground(intent, scene, overrides)
        ids = next(e.scene_object_ids for e in task.entities if e.entity_id == target)
        by_id = {obj.object_id_in_scene: obj for obj in scene.objects}
        selected = [by_id[object_id] for object_id in ids]
        if target in external_relations:
            selected = SceneRelationResolver().resolve(selected, external_relations[target], scene, entity_id=target)
        return selected
