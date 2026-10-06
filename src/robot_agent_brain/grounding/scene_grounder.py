from ..contracts.grounded_task import GroundedEntity, GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import QuantityMode, TaskIntent
from .scene_relation_resolver import SceneRelationResolver

def discover_candidates(entity, scene: SceneConfig):
    available = [o for o in scene.objects if o.scene_object_id not in entity.exclude_scene_object_ids]
    name = entity.semantic_name.casefold()
    exact = [o for o in available if o.semantic_name.casefold() == name or o.scene_object_id == entity.semantic_name]
    aliases = {a.casefold() for a in entity.aliases} | {name}
    alias = [o for o in available if aliases.intersection({o.semantic_name.casefold(), *[a.casefold() for a in o.properties.get("aliases", [])]})]
    category = [o for o in available if o.category.casefold() == entity.category.casefold()]
    # A supplied color is a constraint even on exact name matches.
    for level in ((category,) if entity.category_only else (exact, alias)):
        if level:
            return [o for o in level if not entity.color or str(o.properties.get("color", "")).casefold() == entity.color.casefold()]
    return []

class GroundingAmbiguous(ValueError):
    def __init__(self, entity, candidates):
        self.entity, self.candidates = entity, candidates
        super().__init__(f"grounding_ambiguous: entity={entity.entity_id} candidates={[o.scene_object_id for o in candidates]}")

class SceneGrounder:
    def __init__(self, relation_resolver=None):
        self.relations = relation_resolver or SceneRelationResolver()

    discover_candidates = staticmethod(discover_candidates)

    def ground(self, intent: TaskIntent, scene: SceneConfig, bindings_override=None) -> GroundedTask:
        overrides = bindings_override or {}
        by_entity = {e.entity_id: e for e in intent.entities}
        by_object = {o.scene_object_id: o for o in scene.objects}
        resolved, visiting = {}, set()
        def bind(entity_id):
            if entity_id in resolved:
                return resolved[entity_id]
            if entity_id in visiting:
                raise ValueError("scene_relation_reference_cycle")
            visiting.add(entity_id)
            entity = by_entity[entity_id]
            if entity_id in overrides:
                ids = overrides[entity_id]
                if not ids or any(i not in by_object for i in ids):
                    raise ValueError("grounding_missing: stale binding")
                eligible = {o.scene_object_id for o in discover_candidates(entity, scene)}
                if len(ids) != len(set(ids)) or not set(ids) <= eligible:
                    raise ValueError("grounding_binding_invalid: " + entity_id)
                candidates = [by_object[i] for i in ids]
            else:
                candidates = discover_candidates(entity, scene)
            relations = []
            for rel in intent.spatial_relations:
                if rel.scope != "selection" or rel.subject != entity_id:
                    continue
                if rel.reference:
                    refs = bind(rel.reference)
                    if len(refs) != 1:
                        raise ValueError("scene_relation_reference_ambiguous")
                    rel = rel.model_copy(update={"reference": refs[0].scene_object_id})
                relations.append(rel)
            candidates = self.relations.resolve(candidates, relations, scene, entity_id)
            if not candidates:
                raise ValueError("grounding_missing: " + entity_id)
            if entity.quantity_mode == QuantityMode.ALL:
                count = len(candidates) if entity.all_available else entity.count
                if len(candidates) < count:
                    raise ValueError("grounding_missing: insufficient members for " + entity_id)
                if len(candidates) > count:
                    raise GroundingAmbiguous(entity, candidates)
            elif len(candidates) != 1:
                raise GroundingAmbiguous(entity, candidates)
            resolved[entity_id] = candidates
            visiting.remove(entity_id)
            return candidates
        entities = []
        for entity in intent.entities:
            members = bind(entity.entity_id)
            entities.append(GroundedEntity(
                entity_id=entity.entity_id, semantic_name=entity.semantic_name,
                scene_object_id=members[0].scene_object_id,
                scene_object_ids=[o.scene_object_id for o in members],
                asset_id=members[0].asset_id, category=members[0].category,
                category_only=entity.category_only,
                model_scale=members[0].transform.scale,
            ))
        return GroundedTask(instruction=intent.instruction, entities=entities,
                            operations=intent.operations, spatial_relations=intent.spatial_relations,
                            scene_id=scene.scene_id, scene_version=scene.scene_version)
