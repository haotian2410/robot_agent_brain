"""Shared selection using Scene Semantic, never display or resource names."""
from ..contracts.scene import SceneConfig
from ..contracts.spatial import ResolvedSelectionRelation
from ..contracts.task_intent import QuantityMode, TaskEntity
from ..scene.component_access import SceneIndex
from .scene_relation_resolver import SceneRelationResolver

# A single extremum/nearest phrase describes the result cardinality, not the
# size of the candidate pool.
SELECTION_RELATIONS = {"leftmost", "rightmost", "frontmost", "backmost",
                       "highest", "lowest", "nearest", "farthest", "near"}


def has_selection_relation(relations, identifier):
    return any(relation.scope == "selection" and relation.subject == identifier
               and relation.relation.value in SELECTION_RELATIONS for relation in relations)


def without_colour(entity: TaskEntity) -> TaskEntity:
    # Colour words inside ``tags`` are already split out before scoring, so
    # clearing the field is the whole relaxation.
    return entity.model_copy(update={"color": None})


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
    if not any((entity.semantic_name, entity.tags, entity.aliases, entity.color)) and not entity.category_only:
        # A live edit can point at instances ("把7放到13里") without describing
        # them. Nothing below can match an empty description, so honour the ids
        # and let bind() reject the ones absent from (or excluded from) the scene.
        requested = set(entity.scene_object_ids)
        if requested:
            # The id alone is trusted, but the slug the parser used for it is a
            # name too: refuse ids that point somewhere else by that evidence.
            ident = canonicalize_name(entity.entity_id)
            same_name = {obj.object_id_in_scene for obj in all_available
                         if ident and canonicalize_name(
                             index.semantic(obj.object_id_in_scene).semantic_name) == ident}
            if same_name and not requested <= same_name:
                return []
            return [obj for obj in all_available if obj.object_id_in_scene in requested]
    def resolve_asset(obj):
        if assets is None or index.metadata_ref(obj.object_id_in_scene) is None:
            return None
        kind = index.metadata_type(obj.object_id_in_scene)
        ref = index.metadata_ref(obj.object_id_in_scene)
        try:
            return assets.resolve(ref, kind) if kind else assets.resolve(ref)
        except (ValueError, AttributeError):
            return None

    def paintable(value):
        from ..scene.colors import ColorResolver
        try:
            ColorResolver.resolve(value)
        except ValueError:
            return False
        return True

    def features(candidates, ignore_colour=False):
        from ..scene.colors import ColorEvidenceResolver, PALETTE, color_name
        from ..scene.asset_features import tag_overlap_score
        requested = ([entity.color] if entity.color else []) + [tag for tag in entity.tags if color_name(tag) in PALETTE]
        # A word the paint system cannot express is not a colour constraint at all.
        # Only a name that can be painted enters the evidence check, so 彩色 never
        # turns into a mismatch against the apples that did declare a colour.
        colors = [] if ignore_colour else [value for value in requested if paintable(value)]
        other_tags = [tag for tag in entity.tags if color_name(tag) not in PALETTE]
        evidence = ColorEvidenceResolver(assets)
        kept = []
        saw_color_evidence = saw_tag_evidence = False
        for obj in candidates:
            # Unknown evidence never counts as a match, but it must not veto the
            # siblings that did declare one: a recolored object sitting next to
            # two untouched ones used to abort the entire selection.
            color_matches = [evidence.matches(value, obj, index) for value in colors]
            saw_color_evidence = saw_color_evidence or any(value is not None for value in color_matches)
            if not all(color_matches):
                continue
            score = 0
            if other_tags:
                asset = resolve_asset(obj)
                if asset is None:
                    continue
                saw_tag_evidence = True
                score = tag_overlap_score(asset, other_tags)
                if score == 0:
                    continue
            kept.append((obj, score))
        if not kept:
            # Nobody in the pool declared a colour, so the colour word carries no
            # information here: the paint of a texture is not something this system
            # can measure.  Match the subject instead of refusing the turn -- an
            # untouched 红苹果 request is answered by 「哪个苹果?」, never by an error.
            if candidates and colors and not saw_color_evidence:
                return features(candidates, ignore_colour=True)
            if candidates and other_tags and not saw_tag_evidence:
                raise ValueError("grounding_evidence_missing: tags")
            return []
        # A synonym tag such as "杯子" is shared by every mug, so overlap alone
        # cannot separate them. Only the distinguishing tags raise one asset
        # above the rest; keeping the best score avoids a false ambiguity.
        best = max(score for _, score in kept)
        return [obj for obj, score in kept if score == best]
    if entity.category_only:
        return features(available)
    def by_tags(pool):
        """Tag-overlap matching, the prompt's primary signal, best score wins."""
        from ..scene.asset_features import tag_overlap_score
        if not entity.tags or assets is None:
            return []
        scored = []
        for obj in pool:
            asset = resolve_asset(obj)
            if asset is None:
                continue
            score = tag_overlap_score(asset, entity.tags)
            if score > 0:
                scored.append((obj, score))
        if not scored:
            return []
        max_score = max(s for _, s in scored)
        return [obj for obj, s in scored if s == max_score]

    name = canonicalize_name(entity.semantic_name)

    # Tag-based matching path: when semantic_name is empty but tags are present
    if not name and entity.tags:
        return features(by_tags(available))

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
    by_name = features(matched + [obj for obj in named if obj.object_id_in_scene not in matched_ids])
    if by_name:
        return by_name
    # The slug the parser used can still miss the scene: 「绿色苹果」 arrives as
    # ``green_apple`` while every instance carries ``apple``.  Tags widen what
    # the name gate could not reach, then still obey the colour/tag filters.
    widened_ids = {obj.object_id_in_scene for obj in available}
    widened_ids |= {obj.object_id_in_scene for obj in named}
    pool = [obj for obj in all_available if obj.object_id_in_scene in widened_ids]
    return features(by_tags(pool))


class SemanticEntitySelector:
    def __init__(self, relation_resolver=None, *, aliases=None, category_aliases=None, assets=None,
                 scene_reference_catalog=None, table_metadata_ref=None):
        self.assets = assets
        self.relations = relation_resolver or SceneRelationResolver(assets)
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}
        from .scene_reference_resolver import SceneReferenceResolver
        self.reference_resolver = SceneReferenceResolver(scene_reference_catalog,
                                                         table_metadata_ref=table_metadata_ref)

    def select(self, entity_id, entities, relations, scene, *, bindings_override=None, resolved_relations=None,
               allow_description_fallback=False):
        overrides = bindings_override or {}
        by_entity = {entity.entity_id: entity for entity in entities}
        by_object = {obj.object_id_in_scene: obj for obj in scene.objects}
        resolved, visiting = {}, set()
        def relax_colour(entity):
            """Re-select without the colour term, but only where it cannot pick arbitrarily.

            「红色的苹果」 in a scene where no apple is red must not become an arbitrary
            apple: either the sentence already pins one down with an extremum/near
            relation, or the colourless pool holds a single object.  Bulk quantities
            never relax, because operating on every apple because none was red would
            act on objects the user excluded.
            """
            if entity.quantity_mode is not QuantityMode.SINGLE:
                return []
            candidates = discover_candidates(without_colour(entity), scene, self.category_aliases,
                                             aliases=self.aliases, assets=self.assets)
            if len(candidates) == 1 or has_selection_relation(relations, entity.entity_id):
                return candidates
            return []
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
            if not eligible and entity.color and allow_description_fallback:
                eligible = relax_colour(entity)
            if entity.scene_object_ids:
                requested_ids = entity.scene_object_ids
                if (len(requested_ids) != len(set(requested_ids))
                        or not set(requested_ids) <= {obj.object_id_in_scene for obj in eligible}):
                    raise ValueError("grounding_binding_invalid: " + identifier)
                eligible = [obj for obj in eligible if obj.object_id_in_scene in set(requested_ids)]
            if identifier in overrides:
                ids = overrides[identifier]
                if not ids or any(type(value) is not int or value not in by_object for value in ids):
                    raise ValueError("grounding_missing: stale binding")
                # A pronoun carries no description of its own -- Qwen answers 「把它放到篮子里」
                # with dialogue_ref=true and an empty semantic_name, because only the previous
                # turn knows the witness.  Requiring such an entity's Python binding to fall
                # inside its own candidate pool compares ids against the empty set that an
                # undescribed entity discovers, so it rejected the correct banana.  An entity
                # that does describe itself keeps the subset check, which is what catches a
                # stale binding that has drifted onto a different kind of object.
                undescribed = (not any((entity.semantic_name, entity.tags, entity.aliases, entity.color))
                               and not entity.category_only)
                if (len(ids) != len(set(ids)) or set(ids) & set(entity.exclude_scene_object_ids)
                        or (not undescribed
                            and not set(ids) <= {obj.object_id_in_scene for obj in eligible})):
                    raise ValueError("grounding_binding_invalid: " + identifier)
                candidates = [by_object[value] for value in ids]
            else:
                candidates = eligible
            # Scene reference filters must narrow the pool before extrema and
            # before SceneGrounder checks the requested result cardinality.
            selected_relations = list((resolved_relations or {}).get(identifier, []))
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
            result_selector = any(item.relation.value in SELECTION_RELATIONS
                                  for item in selected_relations)
            # ``all_available`` plus an extremum relation means “choose one
            # result from the current complete candidate set”.  A provider
            # may report the pre-filter count while dialogue/context removes
            # an already-satisfied instance; requiring the remaining pool to
            # equal that stale count incorrectly rejects valid phrases such
            # as “将距离杯子最远的那个苹果设为蓝色”.  An explicit
            # “两个苹果中最右边的那个” still keeps the exact pool-count
            # check because it is not marked all_available.
            selection_from_all = result_selector and entity.all_available
            if (entity.quantity_mode == QuantityMode.CANDIDATE_POOL
                    and not ((entity.count == 1 and result_selector) or selection_from_all)
                    and len(candidates) != entity.count):
                raise ValueError("grounding_candidate_pool_count_mismatch: " + identifier)
            candidates = self.relations.resolve(candidates, selected_relations, scene, identifier)
            resolved[identifier] = candidates
            visiting.remove(identifier)
            return candidates
        return bind(entity_id)
