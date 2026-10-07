"""Shared candidate and relation selection, without robot cardinality."""
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import QuantityMode
from .scene_relation_resolver import SceneRelationResolver

def discover_candidates(entity, scene: SceneConfig, category_aliases=None, *, aliases=None):
    names = {key.strip().casefold(): value.strip().casefold() for key, value in (aliases or {}).items()}
    def canonicalize_name(value):
        normalized = value.strip().casefold()
        return names.get(normalized, normalized)
    categories = {key.strip().casefold():value.strip().casefold() for key,value in (category_aliases or {}).items()}
    required_category = categories.get(entity.category.strip().casefold(), entity.category.strip().casefold())
    available = [o for o in scene.objects if o.scene_object_id not in entity.exclude_scene_object_ids
                 and categories.get(o.category.casefold(), o.category.casefold()) == required_category]
    name = canonicalize_name(entity.semantic_name)
    exact = [o for o in available if canonicalize_name(o.semantic_name) == name or o.scene_object_id == entity.semantic_name]
    requested_names = {canonicalize_name(a) for a in entity.aliases} | {name}
    # Catalog aliases are global language mappings; object aliases remain
    # instance-local additions. Neither layer is copied into scene properties.
    alias = [o for o in available if requested_names.intersection({canonicalize_name(o.semantic_name), *[canonicalize_name(a) for a in o.properties.get("aliases", [])]})]
    category = available
    # A supplied color is a constraint even on exact name matches.
    for level in ((category,) if entity.category_only else (exact, alias)):
        if level:
            return [o for o in level if not entity.color or str(o.properties.get("color", "")).casefold() == entity.color.casefold()]
    return []

class SemanticEntitySelector:
    def __init__(self, relation_resolver=None, *, aliases=None, category_aliases=None):
        self.relations = relation_resolver or SceneRelationResolver()
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}

    def select(self, entity_id, entities, relations, scene, *, bindings_override=None):
        overrides = bindings_override or {}
        by_entity = {e.entity_id: e for e in entities}
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
                eligible = {o.scene_object_id for o in discover_candidates(entity, scene, self.category_aliases, aliases=self.aliases)}
                if len(ids) != len(set(ids)) or not set(ids) <= eligible:
                    raise ValueError("grounding_binding_invalid: " + entity_id)
                candidates = [by_object[i] for i in ids]
            else:
                candidates = discover_candidates(entity, scene, self.category_aliases, aliases=self.aliases)
            if entity.quantity_mode == QuantityMode.CANDIDATE_POOL and len(candidates) != entity.count:
                raise ValueError("grounding_candidate_pool_count_mismatch: " + entity_id)
            selected_relations = []
            for rel in relations:
                if rel.scope != "selection" or rel.subject != entity_id:
                    continue
                if rel.reference:
                    refs = bind(rel.reference)
                    if len(refs) != 1:
                        raise ValueError("scene_relation_reference_ambiguous")
                    rel = rel.model_copy(update={"reference": refs[0].scene_object_id})
                selected_relations.append(rel)
            candidates = self.relations.resolve(candidates, selected_relations, scene, entity_id)
            resolved[entity_id] = candidates
            visiting.remove(entity_id)
            return candidates
        return bind(entity_id)
