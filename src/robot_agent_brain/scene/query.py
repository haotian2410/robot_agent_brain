from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig
from ..contracts.turn import SceneQueryIntent
from ..contracts.task_intent import TaskIntent
from ..grounding.semantic_entity_selector import SemanticEntitySelector

class SceneQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_type: str
    count: int | None = None
    exists: bool | None = None
    object_ids: list[str] = Field(default_factory=list)
    positions: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    states: dict[str, dict] = Field(default_factory=dict)

class SceneQueryEngine:
    def __init__(self, *, aliases=None, category_aliases=None):
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}

    def query(self, intent: SceneQueryIntent, scene: SceneConfig, dialogue=None) -> SceneQueryResult:
        if scene is None:
            raise ValueError("scene_required")
        task = TaskIntent(instruction="query", entities=intent.entities, operations=[], spatial_relations=intent.relations)
        overrides = dialogue.bindings(task, scene) if dialogue else {}
        items = SemanticEntitySelector(aliases=self.aliases, category_aliases=self.category_aliases).select(
            intent.target, intent.entities, intent.relations, scene, bindings_override=overrides)
        return SceneQueryResult(query_type=intent.query_type, count=len(items) if intent.query_type == "count" else None, exists=bool(items) if intent.query_type == "existence" else None, object_ids=[item.scene_object_id for item in items], positions={item.scene_object_id: item.transform.position for item in items} if intent.query_type == "position" else {}, states={item.scene_object_id: dict(item.properties) for item in items} if intent.query_type == "state" else {})
