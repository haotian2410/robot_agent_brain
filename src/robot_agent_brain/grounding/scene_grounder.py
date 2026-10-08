from ..contracts.grounded_task import GroundedEntity, GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import QuantityMode, TaskIntent
from ..scene.component_access import SceneIndex
from ..scene.scene_graph import world_transform
from .scene_relation_resolver import SceneRelationResolver

from .semantic_entity_selector import SemanticEntitySelector, discover_candidates

class GroundingAmbiguous(ValueError):
    def __init__(self, entity, candidates):
        self.entity, self.candidates = entity, candidates
        super().__init__(f"grounding_ambiguous: entity={entity.entity_id} candidates={[o.object_id_in_scene for o in candidates]}")

class SceneGrounder:
    def __init__(self, relation_resolver=None, *, aliases=None, category_aliases=None):
        self.relations = relation_resolver or SceneRelationResolver()
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}

    discover_candidates = staticmethod(discover_candidates)

    def ground(self, intent: TaskIntent, scene: SceneConfig, bindings_override=None) -> GroundedTask:
        selector = SemanticEntitySelector(self.relations, aliases=self.aliases, category_aliases=self.category_aliases)
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
        index = SceneIndex(scene)
        for entity in intent.entities:
            members = bind(entity.entity_id)
            primary = members[0].object_id_in_scene
            semantic = index.semantic(primary)
            entities.append(GroundedEntity(
                entity_id=entity.entity_id, semantic_name=semantic.semantic_name,
                scene_object_id=primary,
                scene_object_ids=[o.object_id_in_scene for o in members],
                metadata_ref=index.metadata_ref(primary), category=semantic.category,
                category_only=entity.category_only,
                model_scale=world_transform(scene, primary).scale,
            ))
        return GroundedTask(instruction=intent.instruction, entities=entities,
                            operations=intent.operations, spatial_relations=intent.spatial_relations,
                            scene_id=scene.scene_id, scene_version=scene.scene_version)
