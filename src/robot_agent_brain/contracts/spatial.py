from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator
from .scene import SceneId

# Tabletop quadrants/halves are one vocabulary: the editor resolves them into
# concrete candidate positions, while a robot task only records the request.
TABLETOP_REGIONS: tuple[str, ...] = (
    "left_half", "right_half", "front_half", "back_half",
    "left_front", "right_front", "left_back", "right_back",
)
TabletopRegion = Literal[*TABLETOP_REGIONS]
PLACEMENT_TARGET_KINDS: tuple[str, ...] = (
    "container_interior", "support_surface", "relative_object", "free_space",
)
PlacementTargetKind = Literal[*PLACEMENT_TARGET_KINDS]
# ``center`` is a hard constraint; ``any`` permits deterministic grid search.
PLACEMENT_HINTS: tuple[str, ...] = ("center", "any")
PlacementHint = Literal[*PLACEMENT_HINTS]


class RelationScope(StrEnum):
    SELECTION = "selection"
    GOAL = "goal"
    STATE = "state"


class SpatialRelationType(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    FRONT = "front"
    BACK = "back"
    UP = "up"
    DOWN = "down"
    LEFTMOST = "leftmost"
    RIGHTMOST = "rightmost"
    FRONTMOST = "frontmost"
    BACKMOST = "backmost"
    HIGHEST = "highest"
    LOWEST = "lowest"
    NEAREST = "nearest"
    FARTHEST = "farthest"
    INSIDE = "inside"
    ON = "on"
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    FRONT_OF = "front_of"
    BEHIND = "behind"
    ABOVE = "above"
    BELOW = "below"
    NEAR = "near"


# A half/aspect relation filters the candidate set by world geometry; with a
# reference it splits around that reference instead of the world origin. An
# extremum always compares the candidate set itself, so its reference is unused.
HALF_SPATIAL_RELATIONS = frozenset({
    SpatialRelationType.LEFT, SpatialRelationType.RIGHT, SpatialRelationType.FRONT,
    SpatialRelationType.BACK, SpatialRelationType.UP, SpatialRelationType.DOWN,
})
EXTREME_SPATIAL_RELATIONS = frozenset({
    SpatialRelationType.LEFTMOST, SpatialRelationType.RIGHTMOST, SpatialRelationType.FRONTMOST,
    SpatialRelationType.BACKMOST, SpatialRelationType.HIGHEST, SpatialRelationType.LOWEST,
})
UNARY_SPATIAL_RELATIONS = HALF_SPATIAL_RELATIONS | EXTREME_SPATIAL_RELATIONS
BINARY_SPATIAL_RELATIONS = frozenset(
    item for item in SpatialRelationType if item not in UNARY_SPATIAL_RELATIONS)


class SpatialRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: RelationScope = RelationScope.SELECTION
    subject: str
    relation: SpatialRelationType
    reference: str | None = None

    @model_validator(mode="after")
    def validate_reference(self):
        if self.relation in BINARY_SPATIAL_RELATIONS and self.reference is None:
            raise ValueError(f"task_semantic_invalid: {self.relation.value} requires reference")
        if self.reference is not None and self.reference == self.subject:
            raise ValueError("task_semantic_invalid: relation subject and reference must differ")
        return self


class ResolvedSelectionRelation(BaseModel):
    """Internal concrete relation; semantic references stay strings in Task."""
    model_config = ConfigDict(extra="forbid")
    relation: SpatialRelationType
    reference_object_id: SceneId | None = None

    @model_validator(mode="after")
    def validate_reference(self):
        if self.relation not in UNARY_SPATIAL_RELATIONS and self.reference_object_id is None:
            raise ValueError("scene_relation_reference_missing")
        return self
