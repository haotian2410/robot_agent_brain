from ..contracts.grounded_task import GroundedEntity, GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import QuantityMode, TaskIntent
from ..scene.component_access import SceneIndex
from ..scene.scene_graph import world_transform
from .scene_relation_resolver import SceneRelationResolver
from ..asset_name_normalization import canonical_name

from .semantic_entity_selector import SemanticEntitySelector, discover_candidates

class GroundingAmbiguous(ValueError):
    def __init__(self, entity, candidates, *, reason="multiple_candidates"):
        self.entity, self.candidates, self.reason = entity, candidates, reason
        super().__init__(f"grounding_ambiguous: entity={entity.entity_id} candidates="
                         f"{[o.object_id_in_scene for o in candidates]} reason={reason}")

class SceneGrounder:
    def __init__(self, relation_resolver=None, *, aliases=None, category_aliases=None, assets=None,
                 scene_reference_catalog=None, table_metadata_ref=None):
        self.assets = assets
        self.relations = relation_resolver or SceneRelationResolver(assets)
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}
        self.scene_reference_catalog = scene_reference_catalog
        self.table_metadata_ref = table_metadata_ref
        self.last_selection_decisions = []

    discover_candidates = staticmethod(discover_candidates)

    def ground(self, intent: TaskIntent, scene: SceneConfig, bindings_override=None, *, resolved_relations=None,
               prefer_auto_resolve: bool = False, logical_task_id: str = "", step_id: str = "ground") -> GroundedTask:
        # The decision is part of durable turn evidence, not merely a local
        # grounding detail. Reset per invocation so a retry cannot reuse a
        # choice from a different semantic request.
        self.last_selection_decisions = []
        selector = SemanticEntitySelector(self.relations, aliases=self.aliases, category_aliases=self.category_aliases,
                                         assets=self.assets, scene_reference_catalog=self.scene_reference_catalog,
                                         table_metadata_ref=self.table_metadata_ref)
        def bind(entity_id):
            entity = next(e for e in intent.entities if e.entity_id == entity_id)
            # An action has to land on something, so a colour nobody declared may
            # relax to the pinned-down instance.  ``SceneQueryEngine`` deliberately
            # leaves this off: counting 「有几个红苹果」 as every apple would answer
            # with a wrong number instead of a miss.
            candidates = selector.select(entity_id, intent.entities, intent.spatial_relations, scene,
                                         bindings_override=bindings_override, resolved_relations=resolved_relations,
                                         allow_description_fallback=True)
            if not candidates:
                raise ValueError("grounding_missing: " + entity_id)
            selection_relations = [relation for relation in intent.spatial_relations
                                   if relation.scope == "selection" and relation.subject == entity.entity_id]
            has_selection_constraint = bool(selection_relations)
            if entity.quantity_mode == QuantityMode.ALL:
                count = len(candidates) if entity.all_available else entity.count
                if len(candidates) < count:
                    raise ValueError("grounding_missing: insufficient members for " + entity_id)
                if len(candidates) > count:
                    raise GroundingAmbiguous(entity, candidates)
            elif len(candidates) != 1:
                # A relation that still leaves multiple candidates is a tie or
                # a half-plane selection (left/right).  It is not safe to use
                # the deterministic auto-resolve policy for it.  Likewise,
                # three or more unqualified candidates require an explicit
                # extremum/description even when the session opted in.
                # Automatic session policy is deliberately not a substitute for
                # user evidence.  Even with prefer_auto_resolve enabled, two
                # unqualified candidates must be named by a comparative/unique
                # description (which the selector has already applied) and ties
                # must remain actionable clarifications.
                relation = selection_relations[0].relation.value if selection_relations else None
                reason = (f"{relation}_tie" if relation in {
                    "leftmost", "rightmost", "frontmost", "backmost",
                    "highest", "lowest", "nearest", "farthest"
                } else "selection_not_unique" if relation else "multiple_candidates")
                raise GroundingAmbiguous(entity, candidates, reason=reason)
            return candidates
        entities = []
        index = SceneIndex(scene)
        def grounded(entity_id, members, category_only=False):
            primary = members[0].object_id_in_scene
            semantic = index.semantic(primary)
            return GroundedEntity(
                entity_id=entity_id, semantic_name=canonical_name(semantic.semantic_name, self.aliases),
                scene_object_id=primary,
                scene_object_ids=[o.object_id_in_scene for o in members],
                metadata_ref=index.metadata_ref(primary), metadata_type=index.metadata_type(primary), category=semantic.category,
                category_only=category_only,
                model_scale=world_transform(scene, primary).scale,
            )
        for entity in intent.entities:
            entities.append(grounded(entity.entity_id, bind(entity.entity_id), entity.category_only))
        # An operation role may name an environment reference the contract accepts without a
        # declared entity, and TaskExpander indexes every role, so those references bind here too.
        declared = {entity.entity_id for entity in intent.entities}
        referenced = set()
        for operation in intent.operations:
            referenced.update(value for value in (operation.source, operation.target, operation.destination,
                                                   operation.reference) if value)
            if operation.placement_target is not None and operation.placement_target.reference:
                referenced.add(operation.placement_target.reference)
        for relation in intent.spatial_relations:
            if relation.reference:
                referenced.add(relation.reference)
        for identifier in sorted(referenced - declared):
            members = selector.select(identifier, intent.entities, intent.spatial_relations, scene,
                                      bindings_override=bindings_override, resolved_relations=resolved_relations)
            if len(members) != 1:
                raise ValueError("scene_reference_unresolved: " + identifier)
            entities.append(grounded(identifier, members))
        return GroundedTask(instruction=intent.instruction, entities=entities,
                            hold_constraints=intent.hold_constraints,
                            operations=intent.operations, spatial_relations=intent.spatial_relations,
                            scene_id=scene.scene_id, scene_version=scene.scene_version)
