"""Resolve selection against shared scene facts, retaining ties for clarification."""
import math

from ..contracts.scene import SceneConfig, SceneObject
from ..contracts.spatial import SpatialRelation

class SceneRelationResolver:
    def resolve(self, candidates: list[SceneObject], relations: list[SpatialRelation],
                scene: SceneConfig, entity_id: str) -> list[SceneObject]:
        selected = list(candidates)
        by_id = {o.scene_object_id: o for o in scene.objects}
        for relation in relations:
            if relation.subject != entity_id or relation.scope != "selection":
                continue
            if not selected:
                return []
            kind = relation.relation.value
            position = lambda o: o.transform.position
            halves = {"left": (0, -1), "right": (0, 1), "front": (1, 1),
                      "back": (1, -1), "up": (2, 1), "down": (2, -1)}
            extrema = {"leftmost": (0, min), "rightmost": (0, max),
                       "frontmost": (1, max), "backmost": (1, min),
                       "highest": (2, max), "lowest": (2, min)}
            if kind in halves:
                axis, sign = halves[kind]
                selected = [o for o in selected if position(o)[axis] * sign > 0]
            elif kind in extrema:
                axis, choose = extrema[kind]
                value = choose(position(o)[axis] for o in selected)
                selected = [o for o in selected if math.isclose(position(o)[axis], value, abs_tol=1e-9)]
            else:
                reference = by_id.get(relation.reference)
                if reference is None:
                    raise ValueError("scene_relation_reference_missing: " + str(relation.reference))
                selected = [o for o in selected if o.scene_object_id != reference.scene_object_id]
                if not selected:
                    return []
                if kind in {"nearest", "farthest"}:
                    scores = {o.scene_object_id: math.dist(position(o)[:2], position(reference)[:2]) for o in selected}
                    value = (min if kind == "nearest" else max)(scores.values())
                    selected = [o for o in selected if math.isclose(scores[o.scene_object_id], value, abs_tol=1e-9)]
                elif kind in {"inside", "on"}:
                    key = "container_membership" if kind == "inside" else "support"
                    def evidence(o):
                        membership = o.properties.get(key)
                        if key in o.properties:
                            return membership == reference.scene_object_id or (isinstance(membership, list) and reference.scene_object_id in membership)
                        if kind == "on" and o.properties.get("support_evaluated") is True:
                            return False
                        return None
                    answers = [(o, evidence(o)) for o in selected]
                    if any(answer is None for _, answer in answers):
                        raise ValueError("scene_relation_evidence_missing: " + kind)
                    selected = [o for o, answer in answers if answer]
                elif kind in {"left_of", "right_of", "front_of", "behind", "above", "below"}:
                    axis, sign = {"left_of": (0,-1), "right_of": (0,1), "front_of": (1,1),
                                  "behind": (1,-1), "above": (2,1), "below": (2,-1)}[kind]
                    selected = [o for o in selected if (position(o)[axis]-position(reference)[axis])*sign > 0]
                else:
                    raise ValueError("scene_relation_evidence_missing: " + kind)
        return selected
