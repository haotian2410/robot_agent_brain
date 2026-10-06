from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig
from ..contracts.turn import SceneQueryIntent
from ..contracts.task_intent import TaskIntent
from ..grounding.scene_grounder import discover_candidates
from ..grounding.scene_relation_resolver import SceneRelationResolver

class SceneQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_type: str
    semantic_name: str | None = None
    count: int | None = None
    exists: bool | None = None
    object_ids: list[str] = Field(default_factory=list)
    positions: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    states: dict[str, dict] = Field(default_factory=dict)

class SceneQueryEngine:
    def __init__(self, *, category_aliases=None):
        self.category_aliases = category_aliases or {}

    def query(self, intent: SceneQueryIntent, scene: SceneConfig, dialogue=None) -> SceneQueryResult:
        if scene is None:
            raise ValueError("scene_required")
        items = [item for item in scene.objects if (intent.referent_scene_object_id is None or item.scene_object_id == intent.referent_scene_object_id) and (intent.semantic_name is None or item.semantic_name.casefold() == intent.semantic_name.casefold()) and (intent.category is None or item.category.casefold() == intent.category.casefold())]
        if intent.target is not None:
            entities = {e.entity_id:e for e in intent.entities}
            task = TaskIntent(instruction="query", entities=intent.entities, operations=[], spatial_relations=intent.relations)
            overrides = dialogue.bindings(task, scene) if dialogue else {}
            active, resolved = set(), {}
            def select(entity_id):
                if entity_id in resolved:
                    return resolved[entity_id]
                if entity_id in active:
                    raise ValueError("scene_relation_reference_cycle")
                active.add(entity_id)
                candidates = discover_candidates(entities[entity_id], scene, self.category_aliases)
                if entity_id in overrides:
                    if not set(overrides[entity_id]) <= {o.scene_object_id for o in candidates}:
                        raise ValueError("grounding_binding_invalid")
                    candidates = [o for o in candidates if o.scene_object_id in overrides[entity_id]]
                relations = []
                for relation in intent.relations:
                    if relation.subject != entity_id:
                        continue
                    if relation.reference:
                        refs = select(relation.reference)
                        if len(refs) != 1:
                            raise ValueError("scene_relation_reference_ambiguous")
                        relation = relation.model_copy(update={"reference":refs[0].scene_object_id})
                    relations.append(relation)
                resolved[entity_id] = SceneRelationResolver().resolve(candidates, relations, scene, entity_id)
                active.remove(entity_id)
                return resolved[entity_id]
            items = select(intent.target)
        return SceneQueryResult(query_type=intent.query_type, semantic_name=intent.semantic_name, count=len(items) if intent.query_type == "count" else None, exists=bool(items) if intent.query_type == "existence" else None, object_ids=[item.scene_object_id for item in items], positions={item.scene_object_id: item.transform.position for item in items} if intent.query_type == "position" else {}, states={item.scene_object_id: dict(item.properties) for item in items} if intent.query_type == "state" else {})
