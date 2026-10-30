"""Shared selection using Scene Semantic, never display or resource names."""
from ..contracts.scene import SceneConfig
from ..contracts.spatial import ResolvedSelectionRelation
from ..contracts.task_intent import QuantityMode
from ..scene.component_access import SceneIndex
from .scene_relation_resolver import SceneRelationResolver


def discover_candidates(entity, scene: SceneConfig, category_aliases=None, *, aliases=None, assets=None):
    names = {key.strip().casefold(): value.strip().casefold() for key, value in (aliases or {}).items()}
    def canonicalize_name(value):
        normalized = value.strip().casefold()
        return names.get(normalized, normalized)
    categories = {key.strip().casefold(): value.strip().casefold() for key, value in (category_aliases or {}).items()}
    def category(value):
        value = value.strip().casefold()
        return categories.get(value, value)
    index = SceneIndex(scene)
    all_available = [obj for obj in index.semantic_objects()
                     if obj.object_id_in_scene not in entity.exclude_scene_object_ids]
    available = [obj for obj in all_available
                 if category(index.semantic(obj.object_id_in_scene).category) == category(entity.category)]
    def features(candidates):
        from ..scene.colors import ColorEvidenceResolver, PALETTE, color_name
        from ..scene.asset_features import matches_features
        colors = ([entity.color] if entity.color else []) + [tag for tag in entity.tags if color_name(tag) in PALETTE]
        other_tags = [tag for tag in entity.tags if color_name(tag) not in PALETTE]
        evidence = ColorEvidenceResolver(assets)
        result = []
        for obj in candidates:
            # Evaluate all relevant candidates so unknown evidence isn't counted as false.
            color_matches = [evidence.matches(value, obj, index) for value in colors]
            tag_match = True
            if other_tags:
                if assets is None or index.metadata_ref(obj.object_id_in_scene) is None:
                    raise ValueError("grounding_evidence_missing: tags")
                kind = index.metadata_type(obj.object_id_in_scene)
                ref = index.metadata_ref(obj.object_id_in_scene)
                asset = assets.resolve(ref, kind) if kind else assets.resolve(ref)
                tag_match = matches_features(asset, entity.model_copy(update={"color": None, "tags": other_tags}))
            if all(color_matches) and tag_match:
                result.append(obj)
        return result
    if entity.category_only:
        return features(available)
    name = canonicalize_name(entity.semantic_name)
    # Scene v1 assets may use a broad protocol category such as ``object``
    # while the task parser uses a useful lexical category such as ``fruit``.
    # An explicit semantic name is stronger evidence than that optional hint;
    # resolve it first and only use category to narrow a real match.
    named = [obj for obj in all_available
             if (getattr(assets, "typed_namespaces", False)
                 or category(index.semantic(obj.object_id_in_scene).category) in {"object", "graspable", "placement"})
             and canonicalize_name(index.semantic(obj.object_id_in_scene).semantic_name) == name]
    exact = [obj for obj in available if canonicalize_name(index.semantic(obj.object_id_in_scene).semantic_name) == name]
    # Imported Scene v1 objects use broad categories while newly added objects
    # use lexical ones. Both are the same named candidates; adding one must not
    # make the imported instances disappear from counts or nearest/farthest.
    exact_ids = {obj.object_id_in_scene for obj in exact}
    exact += [obj for obj in named if obj.object_id_in_scene not in exact_ids]
    if exact:
        return features(exact)
    requested_names = {canonicalize_name(alias) for alias in entity.aliases} | {name}
    named = [obj for obj in all_available
             if (getattr(assets, "typed_namespaces", False)
                 or category(index.semantic(obj.object_id_in_scene).category) in {"object", "graspable", "placement"})
             and canonicalize_name(index.semantic(obj.object_id_in_scene).semantic_name) in requested_names]
    matched = [obj for obj in available if canonicalize_name(index.semantic(obj.object_id_in_scene).semantic_name) in requested_names]
    matched_ids = {obj.object_id_in_scene for obj in matched}
    return features(matched + [obj for obj in named if obj.object_id_in_scene not in matched_ids])


class SemanticEntitySelector:
    def __init__(self, relation_resolver=None, *, aliases=None, category_aliases=None, assets=None,
                 scene_reference_catalog=None, table_metadata_ref=None):
        self.assets = assets
        self.relations = relation_resolver or SceneRelationResolver()
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}
        from .scene_reference_resolver import SceneReferenceResolver
        self.reference_resolver = SceneReferenceResolver(scene_reference_catalog,
                                                         table_metadata_ref=table_metadata_ref)

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
                # Environment references (table/桌面 and configured aliases)
                # are resolved to a concrete scene object rather than being
                # fabricated as task entities.
                bound = self.reference_resolver.resolve(identifier, entities=entities, scene=scene)
                if bound.object_id is None or bound.object_id not in by_object:
                    raise ValueError("scene_reference_unresolved: " + identifier)
                resolved_object = by_object[bound.object_id]
                resolved[identifier] = [resolved_object]
                return resolved[identifier]
            visiting.add(identifier)
            entity = by_entity[identifier]
            eligible = discover_candidates(entity, scene, self.category_aliases, aliases=self.aliases, assets=self.assets)
            if identifier in overrides:
                ids = overrides[identifier]
                if not ids or any(type(value) is not int or value not in by_object for value in ids):
                    raise ValueError("grounding_missing: stale binding")
                if len(ids) != len(set(ids)) or not set(ids) <= {obj.object_id_in_scene for obj in eligible}:
                    raise ValueError("grounding_binding_invalid: " + identifier)
                candidates = [by_object[value] for value in ids]
            else:
                candidates = eligible
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
            # A single extremum/nearest/farthest phrase describes the result
            # cardinality, not the size of the candidate pool.  Older Qwen
            # payloads occasionally encoded it as candidate_pool/count=1;
            # rejecting before applying the selector made ordinary phrases
            # such as “最左边的苹果” fail with an internal pool mismatch.
            selector_relations = {"leftmost", "rightmost", "frontmost", "backmost",
                                  "highest", "lowest", "nearest", "farthest", "near"}
            result_selector = any(item.relation.value in selector_relations
                                  for item in selected_relations)
            if (entity.quantity_mode == QuantityMode.CANDIDATE_POOL
                    and not (entity.count == 1 and result_selector)
                    and len(candidates) != entity.count):
                raise ValueError("grounding_candidate_pool_count_mismatch: " + identifier)
            candidates = self.relations.resolve(candidates, selected_relations, scene, identifier)
            resolved[identifier] = candidates
            visiting.remove(identifier)
            return candidates
        return bind(entity_id)
