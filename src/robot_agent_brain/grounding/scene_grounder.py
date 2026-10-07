from ..contracts.grounded_task import GroundedEntity, GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import QuantityMode, TaskIntent
from .scene_relation_resolver import SceneRelationResolver

from .semantic_entity_selector import SemanticEntitySelector, discover_candidates

class GroundingAmbiguous(ValueError):
    def __init__(self, entity, candidates):
        self.entity, self.candidates = entity, candidates
        super().__init__(f"grounding_ambiguous: entity={entity.entity_id} candidates={[o.scene_object_id for o in candidates]}")

class SceneGrounder:
    def __init__(self, relation_resolver=None, *, category_aliases=None):
        self.relations = relation_resolver or SceneRelationResolver()
        self.category_aliases = category_aliases or {}

    discover_candidates = staticmethod(discover_candidates)

    def ground(self, intent: TaskIntent, scene: SceneConfig, bindings_override=None) -> GroundedTask:
        selector = SemanticEntitySelector(self.relations, category_aliases=self.category_aliases)
        def bind(entity_id):
            entity = next(e for e in intent.entities if e.entity_id == entity_id)
            candidates = selector.select(entity_id, intent.entities, intent.spatial_relations, scene,
                                         bindings_override=bindings_override)
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
