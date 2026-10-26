from __future__ import annotations
import math
from pydantic import BaseModel, ConfigDict, Field
from ..contracts.scene import SceneConfig, SceneId
from .component_access import SceneIndex
from .scene_graph import world_transform
from ..contracts.turn import SceneQueryIntent
from ..contracts.task_intent import TaskIntent
from ..grounding.semantic_entity_selector import SemanticEntitySelector
from ..contracts.spatial import ResolvedSelectionRelation
from ..grounding.scene_relation_resolver import SceneRelationResolver
from .geometry import world_bounds

class SceneQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_type: str
    count: int | None = None
    exists: bool | None = None
    object_ids: list[SceneId] = Field(default_factory=list)
    # JSON object keys are strings on the wire; values retain numeric IDs.
    positions: dict[int, tuple[float, float, float]] = Field(default_factory=dict)
    states: dict[int, dict] = Field(default_factory=dict)
    names: dict[int, str] = Field(default_factory=dict)
    distances_m: dict[int, float] = Field(default_factory=dict)
    reference_object_id: SceneId | None = None
    relation_holds: bool | None = None
    reply: str | None = None
    evidence_source: str = "scene"
    near_distance_m: float | None = None

class SceneQueryEngine:
    def __init__(self, *, aliases=None, category_aliases=None, assets=None, near_distance_m=.2):
        self.assets = assets
        self.aliases = aliases or {}
        self.category_aliases = category_aliases or {}
        self.near_distance_m = near_distance_m

    def query(self, intent: SceneQueryIntent, scene: SceneConfig, dialogue=None) -> SceneQueryResult:
        if scene is None:
            raise ValueError("scene_required")
        task = TaskIntent(instruction="query", entities=intent.entities, operations=[], spatial_relations=intent.relations)
        overrides = dialogue.bindings(task, scene) if dialogue else {}
        selector = SemanticEntitySelector(aliases=self.aliases, category_aliases=self.category_aliases, assets=self.assets)
        items = selector.select(
            intent.target, intent.entities, intent.relations, scene, bindings_override=overrides)
        index = SceneIndex(scene)
        if intent.evidence_source == "image":
            # Image requests are dispatched by the pipeline, never silently answered as if seen.
            raise ValueError("query_visual_evidence_required")
        distances, reference_id, holds, reply = {}, None, None, None
        label = lambda obj: f"{obj.object_name_in_scene}（#{obj.object_id_in_scene}）"
        if intent.query_type == "neighbors":
            reference = self._unique(items, intent.target)
            reference_id = reference.object_id_in_scene
            lo, hi = self._bounds(reference, scene, index)
            support = index.semantic(reference_id).support
            items = []
            for obj in index.semantic_objects():
                oid = obj.object_id_in_scene
                semantic = index.semantic(oid)
                if (oid == reference_id or index.metadata_type(oid) == "robot"
                        or index.component(oid, "Camera") or index.component(oid, "RobotAttachment")
                        or semantic.category.casefold() in {"robot", "camera", "light", "table", "platform"}
                        or semantic.semantic_name.casefold() in {"table", "work_table", "robot_pedestal"}):
                    continue
                if semantic.support == reference_id or support == oid:
                    continue
                if support is not None and semantic.support is not None and support != semantic.support:
                    continue
                low, high = self._bounds(obj, scene, index)
                # Overlapping footprints are not evidence of "beside" (inside/above differ).
                if all(min(hi[i], high[i]) - max(lo[i], low[i]) > 1e-9 for i in (0, 1)):
                    continue
                if low[2] > hi[2] + 1e-9 or lo[2] > high[2] + 1e-9:
                    continue
                distance = math.hypot(*(max(lo[i] - high[i], low[i] - hi[i], 0) for i in (0, 1)))
                if distance <= self.near_distance_m + 1e-9:
                    items.append(obj)
                    distances[oid] = distance
            items.sort(key=lambda obj: (distances[obj.object_id_in_scene], obj.object_id_in_scene))
            reply = (f"按桌面投影边界间距 {self.near_distance_m * 100:g} 厘米以内查询，{label(reference)}旁边"
                     + ("有：" + "、".join(label(o) for o in items) + "。" if items else "没有匹配物体。"))
        elif intent.query_type == "relation":
            subject = self._unique(items, intent.target)
            reference = self._unique(selector.select(intent.reference, intent.entities, intent.relations, scene,
                                      bindings_override=overrides), intent.reference)
            reference_id = reference.object_id_in_scene
            if reference_id == subject.object_id_in_scene:
                raise ValueError("query_subject_reference_same")
            holds = bool(SceneRelationResolver().resolve([subject], [ResolvedSelectionRelation(
                relation=intent.predicate, reference_object_id=reference_id)], scene))
            wording = {"left_of": "左边", "right_of": "右边", "front_of": "前方", "behind": "后方",
                       "above": "上方", "below": "下方", "on": "支撑面上"}[intent.predicate]
            reply = f"{'是' if holds else '否'}，按场景世界坐标，{label(subject)}{'在' if holds else '不在'}{label(reference)}的{wording}。"
        elif intent.query_type == "selection":
            spatial = next((r for r in intent.relations if r.subject == intent.target and r.relation.value in {"nearest", "farthest"}), None)
            if spatial:
                reference = self._unique(selector.select(spatial.reference, intent.entities, intent.relations, scene,
                                          bindings_override=overrides), spatial.reference)
                reference_id = reference.object_id_in_scene
                origin = world_transform(scene, reference_id).position[:2]
                distances = {o.object_id_in_scene: math.dist(world_transform(scene, o.object_id_in_scene).position[:2], origin) for o in items}
            reply = ("匹配对象：" + "、".join(label(o) + (f"，水平中心距离 {distances[o.object_id_in_scene]:.3f} 米" if distances else "") for o in items)
                     + ("（并列）" if len(items) > 1 else "") + "。") if items else "没有匹配对象。"
        ids = [item.object_id_in_scene for item in items]
        return SceneQueryResult(
            query_type=intent.query_type,
            names={obj.object_id_in_scene: obj.object_name_in_scene for obj in items},
            distances_m=distances, reference_object_id=reference_id, relation_holds=holds, reply=reply,
            near_distance_m=self.near_distance_m if intent.query_type == "neighbors" else None,
            count=len(items) if intent.query_type == "count" else None,
            exists=bool(items) if intent.query_type == "existence" else None,
            object_ids=ids,
            positions={i: world_transform(scene, i).position for i in ids}
            if intent.query_type == "position" else {},
            states={i: {"support": index.semantic(i).support} for i in ids}
            if intent.query_type == "state" else {})

    @staticmethod
    def _unique(items, entity):
        if len(items) != 1:
            raise ValueError("query_reference_ambiguous: " + entity + "; 候选：" +
                             ", ".join(f"{o.object_name_in_scene} #{o.object_id_in_scene}" for o in items))
        return items[0]

    def _bounds(self, obj, scene, index):
        if self.assets is None or index.metadata_ref(obj.object_id_in_scene) is None:
            raise ValueError("query_geometry_evidence_missing")
        ref, kind = index.metadata_ref(obj.object_id_in_scene), index.metadata_type(obj.object_id_in_scene)
        asset = self.assets.resolve(ref, kind) if kind else self.assets.resolve(ref)
        return world_bounds(asset, world_transform(scene, obj.object_id_in_scene))
