from ..contracts.task_intent import QuantityMode, TaskIntent
from ..contracts.spatial import ResolvedSelectionRelation
from .scene_grounder import SceneGrounder
from .scene_reference_resolver import SceneReferenceResolver


class SceneObjectSelector:
    """Scene edits use robot grounding, including relation and dialogue rules."""

    def __init__(self, *, aliases=None, category_aliases=None, assets=None,
                 scene_reference_catalog=None, table_metadata_ref=None):
        self.assets = assets
        self.aliases = aliases
        self.category_aliases = category_aliases
        self.reference_resolver = SceneReferenceResolver(scene_reference_catalog,
                                                         table_metadata_ref=table_metadata_ref)

    def resolve(self, target, entities, relations, scene, dialogue=None, bindings_override=None,
                *, allow_partial=False):
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
        target_entity = next(entity for entity in entities if entity.entity_id == target)
        partial_count = (allow_partial
                         and target_entity.quantity_mode == QuantityMode.ALL
                         and target_entity.select_count_from_candidates
                         and not target_entity.all_available
                         and not target_entity.scene_object_ids)
        target_entities = [
            entity.model_copy(update={"quantity_mode": "all", "all_available": True})
            if partial_count and entity.entity_id == target else entity
            for entity in entities
        ]
        ranked = []
        if partial_count:
            extrema = {"leftmost", "rightmost", "frontmost", "backmost", "highest", "lowest"}
            ranked = [rel for rel in internal_relations if rel.subject == target and rel.relation in extrema]
            internal_relations = [rel for rel in internal_relations if rel not in ranked]
        intent = TaskIntent(
            instruction="scene object selection",
            entities=[e for e in target_entities if e.entity_id in needed], operations=[],
            spatial_relations=internal_relations,
        )
        local = {key: value for key, value in (bindings_override or {}).items() if key in needed}
        dialogue_intent = intent.model_copy(update={"entities": [e for e in intent.entities if e.entity_id not in local]})
        overrides = dialogue.bindings(dialogue_intent, scene) if dialogue else {}
        overrides.update(local)
        task = SceneGrounder(aliases=self.aliases, category_aliases=self.category_aliases, assets=self.assets,
                             scene_reference_catalog=self.reference_resolver.catalog,
                             table_metadata_ref=self.reference_resolver.table_metadata_ref).ground(
            intent, scene, overrides, resolved_relations=external_relations)
        ids = next(e.scene_object_ids for e in task.entities if e.entity_id == target)
        by_id = {obj.object_id_in_scene: obj for obj in scene.objects}
        selected = [by_id[object_id] for object_id in ids]
        if partial_count:
            if len(selected) < target_entity.count:
                raise ValueError("grounding_missing: insufficient members for " + target)
            selected = sorted(selected, key=lambda obj: obj.object_id_in_scene)
            from ..scene.scene_graph import world_transform
            for relation in reversed(ranked):
                axis, sign = {"leftmost": (0, 1), "rightmost": (0, -1),
                              "frontmost": (1, -1), "backmost": (1, 1),
                              "highest": (2, -1), "lowest": (2, 1)}[relation.relation]
                selected.sort(key=lambda obj: sign * world_transform(scene, obj.object_id_in_scene).position[axis])
            selected = selected[:target_entity.count]
        return selected
