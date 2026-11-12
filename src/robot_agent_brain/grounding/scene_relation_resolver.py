"""Resolve concrete selection using world transforms and protocol evidence."""
import math

from ..contracts.scene import SceneConfig, SceneObject
from ..contracts.spatial import ResolvedSelectionRelation
from ..scene.component_access import SceneIndex
from ..scene.geometry import world_bounds
from ..scene.scene_graph import world_transform
from ..scene.spatial_facts import SpatialFactResolver

# How far a candidate's box may hang below a container's floor and still be
# called inside it: a rounding difference in the written-back pose, not an object
# resting on the table beside the basket.
_INSIDE_TOLERANCE_M = 1e-3


class SceneRelationResolver:
    def __init__(self, assets=None):
        # Asset geometry is optional: without it only relations the scene cannot
        # misread are answered, and the caller gets the evidence-missing stop.
        self.facts = SpatialFactResolver(assets) if assets is not None else None

    def _inside(self, obj, container, scene):
        """True/false from both boxes, or None when the scene carries no geometry."""
        if self.facts is None:
            return None
        try:
            candidate = world_bounds(self.facts.asset(obj, scene),
                                     world_transform(scene, obj.object_id_in_scene))
            holder = world_bounds(self.facts.asset(container, scene),
                                  world_transform(scene, container.object_id_in_scene))
        except (ValueError, LookupError):
            return None
        (clow, chigh), (blow, bhigh) = candidate, holder
        for axis in (0, 1):
            # The box has to sit in the opening and be small enough to fit it;
            # a table is never "in" a basket however they overlap.
            if not blow[axis] < (clow[axis] + chigh[axis]) / 2 < bhigh[axis]:
                return False
            if chigh[axis] - clow[axis] >= bhigh[axis] - blow[axis]:
                return False
        # Vertically the candidate rests on the container's floor and stays below
        # its rim; anything above the rim is beside or over it, not in it.
        return blow[2] - _INSIDE_TOLERANCE_M <= clow[2] < bhigh[2]

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
                # An explicit reference (e.g. a table quadrant) must not be
                # silently discarded in favour of the world origin.
                reference = index.object(relation.reference_object_id) if relation.reference_object_id is not None else None
                origin = position(reference)[axis] if reference is not None else 0
                selected = [obj for obj in selected
                            if (reference is None or obj.object_id_in_scene != reference.object_id_in_scene)
                            and (position(obj)[axis] - origin) * sign > 0]
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
                    # The container's box is the evidence: with geometry the relation
                    # discriminates, so 「把篮子里的东西拿出来」 answers from who is
                    # actually in the basket.  Without geometry it can only confirm an
                    # answer that is already unique (the user describing where their own
                    # object sits), and a guess over several candidates is exactly the
                    # misoperation this gate exists to prevent.
                    readings = [(obj, self._inside(obj, reference, scene)) for obj in selected]
                    if any(inside is None for _, inside in readings):
                        if len(selected) > 1:
                            raise ValueError("scene_relation_evidence_missing: inside")
                    else:
                        selected = [obj for obj, inside in readings if inside]
                    # Containment is the whole answer for this relation: the trailing
                    # branches each name a different piece of evidence to check.
                    continue
                if not selected:
                    return []
                if kind in {"nearest", "farthest", "near"}:
                    scores = {obj.object_id_in_scene: math.dist(position(obj)[:2], position(reference)[:2]) for obj in selected}
                    # In a selection relation, “near/靠近” means choose the
                    # closest member of the candidate set.  The query route's
                    # ``neighbors`` relation remains the AABB-boundary
                    # threshold query; this branch is only for selecting one
                    # subject for an edit/task.
                    value = min(scores.values()) if kind in {"nearest", "near"} else max(scores.values())
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
