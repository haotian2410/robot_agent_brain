from enum import StrEnum
from pydantic import BaseModel, ConfigDict, model_validator


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


class SpatialRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: RelationScope = RelationScope.SELECTION
    subject: str
    relation: SpatialRelationType
    reference: str | None = None

    @model_validator(mode="after")
    def validate_reference(self):
        binary = {SpatialRelationType.NEAREST, SpatialRelationType.FARTHEST, SpatialRelationType.INSIDE, SpatialRelationType.ON, SpatialRelationType.LEFT_OF, SpatialRelationType.RIGHT_OF, SpatialRelationType.FRONT_OF, SpatialRelationType.BEHIND, SpatialRelationType.ABOVE, SpatialRelationType.BELOW, SpatialRelationType.NEAR}
        if self.relation in binary and self.reference is None:
            raise ValueError(f"task_semantic_invalid: {self.relation.value} requires reference")
        if self.reference is not None and self.reference == self.subject:
            raise ValueError("task_semantic_invalid: relation subject and reference must differ")
        return self
