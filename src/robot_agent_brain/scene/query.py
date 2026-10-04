from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig
from ..contracts.turn import SceneQueryIntent

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
    def query(self, intent: SceneQueryIntent, scene: SceneConfig) -> SceneQueryResult:
        items = [item for item in scene.objects if (intent.semantic_name is None or item.semantic_name.casefold() == intent.semantic_name.casefold()) and (intent.category is None or item.category.casefold() == intent.category.casefold())]
        return SceneQueryResult(query_type=intent.query_type, semantic_name=intent.semantic_name, count=len(items) if intent.query_type == "count" else None, exists=bool(items) if intent.query_type == "existence" else None, object_ids=[item.scene_object_id for item in items] if intent.query_type in {"position", "state"} else [], positions={item.scene_object_id: item.transform.position for item in items} if intent.query_type == "position" else {}, states={item.scene_object_id: item.properties for item in items} if intent.query_type == "state" else {})
