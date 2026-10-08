"""Shared selection using Scene Semantic, never display or resource names."""
from ..contracts.scene import SceneConfig
from ..contracts.spatial import ResolvedSelectionRelation
from ..contracts.task_intent import QuantityMode
from ..scene.component_access import SceneIndex
from .scene_relation_resolver import SceneRelationResolver


def discover_candidates(entity, scene: SceneConfig, category_aliases=None, *, aliases=None):
    names = {key.strip().casefold(): value.strip().casefold() for key, value in (aliases or {}).items()}
    def canonicalize_name(value):
        normalized = value.strip().casefold()
        return names.get(normalized, normalized)
    categories = {key.strip().casefold(): value.strip().casefold() for key, value in (category_aliases or {}).items()}
    def category(value):
        value = value.strip().casefold()
        return categories.get(value, value)
    index = SceneIndex(scene)
    available = [obj for obj in index.semantic_objects()
                 if obj.object_id_in_scene not in entity.exclude_scene_object_ids
                 and category(index.semantic(obj.object_id_in_scene).category) == category(entity.category)]
    # Neither display names nor forceOverrideColor are reliable color semantics.
    if entity.color:
        raise ValueError("grounding_evidence_missing: color")
    if entity.category_only:
        return available
    name = canonicalize_name(entity.semantic_name)
    exact = [obj for obj in available if canonicalize_name(index.semantic(obj.object_id_in_scene).semantic_name) == name]
    if exact:
        return exact
    requested_names = {canonicalize_name(alias) for alias in entity.aliases} | {name}
    return [obj for obj in available if canonicalize_name(index.semantic(obj.object_id_in_scene).semantic_name) in requested_names]


class SemanticEntitySelector:
    def __init__(self, relation_resolver=None, *, aliases=None, category_aliases=None):
        self.relations = relation_resolver or SceneRelationResolver()
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}

    def select(self, entity_id, entities, relations, scene, *, bindings_override=None):
        overrides = bindings_override or {}
        by_entity = {entity.entity_id: entity for entity in entities}
        by_object = {obj.object_id_in_scene: obj for obj in scene.objects}
        resolved, visiting = {}, set()
        def bind(identifier):
            if identifier in resolved:
                return resolved[identifier]
            if identifier in visiting:
                raise ValueError("scene_relation_reference_cycle")
            if identifier not in by_entity:
                raise ValueError("scene_relation_reference_missing: " + identifier)
            visiting.add(identifier)
            entity = by_entity[identifier]
            eligible = discover_candidates(entity, scene, self.category_aliases, aliases=self.aliases)
            if identifier in overrides:
                ids = overrides[identifier]
                if not ids or any(type(value) is not int or value not in by_object for value in ids):
                    raise ValueError("grounding_missing: stale binding")
                if len(ids) != len(set(ids)) or not set(ids) <= {obj.object_id_in_scene for obj in eligible}:
                    raise ValueError("grounding_binding_invalid: " + identifier)
                candidates = [by_object[value] for value in ids]
            else:
                candidates = eligible
            if entity.quantity_mode == QuantityMode.CANDIDATE_POOL and len(candidates) != entity.count:
                raise ValueError("grounding_candidate_pool_count_mismatch: " + identifier)
            selected_relations = []
            for relation in relations:
                if relation.scope != "selection" or relation.subject != identifier:
                    continue
                reference = None
                if relation.reference is not None:
                    references = bind(relation.reference)
                    if len(references) != 1:
                        raise ValueError("scene_relation_reference_ambiguous")
                    reference = references[0].object_id_in_scene
                selected_relations.append(ResolvedSelectionRelation(
                    relation=relation.relation, reference_object_id=reference))
            candidates = self.relations.resolve(candidates, selected_relations, scene, identifier)
            resolved[identifier] = candidates
            visiting.remove(identifier)
            return candidates
        return bind(entity_id)
