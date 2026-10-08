"""Resolve concrete selection using world transforms and protocol evidence."""
import math

from ..contracts.scene import SceneConfig, SceneObject
from ..contracts.spatial import ResolvedSelectionRelation
from ..scene.component_access import SceneIndex
from ..scene.scene_graph import world_transform


class SceneRelationResolver:
    def resolve(self, candidates: list[SceneObject], relations: list[ResolvedSelectionRelation],
                scene: SceneConfig, entity_id: str | None = None) -> list[SceneObject]:
        # entity_id is only a diagnostic context, not a concrete reference.
        selected = list(candidates)
        index = SceneIndex(scene)
        positions = {}
        def position(obj):
            identifier = obj.object_id_in_scene
            if identifier not in positions:
                positions[identifier] = world_transform(scene, identifier).position
            return positions[identifier]
        halves = {"left": (0, -1), "right": (0, 1), "front": (1, 1),
                  "back": (1, -1), "up": (2, 1), "down": (2, -1)}
        extrema = {"leftmost": (0, min), "rightmost": (0, max),
                   "frontmost": (1, max), "backmost": (1, min),
                   "highest": (2, max), "lowest": (2, min)}
        for relation in relations:
            if not isinstance(relation, ResolvedSelectionRelation):
                raise TypeError("scene_relation_requires_resolved_reference")
            if not selected:
                return []
            kind = relation.relation.value
            if kind in halves:
                axis, sign = halves[kind]
                selected = [obj for obj in selected if position(obj)[axis] * sign > 0]
            elif kind in extrema:
                axis, choose = extrema[kind]
                value = choose(position(obj)[axis] for obj in selected)
                selected = [obj for obj in selected if math.isclose(position(obj)[axis], value, rel_tol=0, abs_tol=1e-9)]
            else:
                try:
                    reference = index.object(relation.reference_object_id)
                except LookupError as exc:
                    raise ValueError(f"scene_relation_reference_missing: {relation.reference_object_id}") from exc
                reference_id = reference.object_id_in_scene
                selected = [obj for obj in selected if obj.object_id_in_scene != reference_id]
                if kind == "inside":
                    raise ValueError("scene_relation_evidence_missing: inside")
                if not selected:
                    return []
                if kind in {"nearest", "farthest"}:
                    scores = {obj.object_id_in_scene: math.dist(position(obj)[:2], position(reference)[:2]) for obj in selected}
                    value = (min if kind == "nearest" else max)(scores.values())
                    selected = [obj for obj in selected if math.isclose(scores[obj.object_id_in_scene], value, rel_tol=0, abs_tol=1e-9)]
                elif kind == "on":
                    semantics = [(obj, index.semantic(obj.object_id_in_scene)) for obj in selected]
                    if any(semantic is None for _, semantic in semantics):
                        raise ValueError("scene_relation_evidence_missing: on")
                    selected = [obj for obj, semantic in semantics if semantic.support == reference_id]
                elif kind in {"left_of", "right_of", "front_of", "behind", "above", "below"}:
                    axis, sign = {"left_of": (0, -1), "right_of": (0, 1), "front_of": (1, 1),
                                  "behind": (1, -1), "above": (2, 1), "below": (2, -1)}[kind]
                    selected = [obj for obj in selected if (position(obj)[axis] - position(reference)[axis]) * sign > 0]
                else:
                    raise ValueError("scene_relation_evidence_missing: " + kind)
        return selected
