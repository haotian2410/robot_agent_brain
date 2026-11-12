"""Control atomic-skill dialect (skill.md): the executable command document.

Brain's semantic skills stay internal; this is the only shape the control
runtime accepts.  Parameter names, units and defaults mirror the control
specification exactly and are never invented here.
"""
from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Any, Literal, Union

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .scene import SceneId

NamedTarget = Literal["home", "end_effector"]
PlanningMethod = Literal["joint", "linear"]
MoveRelation = Literal["above", "below", "front", "behind", "left", "right"]
PutRelation = Literal["at", "front", "behind", "left", "right", "above", "below"]
PoseAxis = Literal["+z", "-z", "+x", "-x", "+y", "-y"]
MotionFrame = Literal["tool", "grasp", "world"]


class AtomicSkillName(StrEnum):
    APPROACH = "approach"
    PICK = "pick"
    LIFT_UP = "lift_up"
    RETREAT = "retreat"
    MOVE_TO = "move_to"
    PUT = "put"
    PULL = "pull"
    PUSH = "push"
    RELEASE = "release"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _finite(value, field):
    if not math.isfinite(value):
        raise ValueError(f"atomic_command_invalid: {field} must be finite")
    return value


class SearchParameters(StrictModel):
    """Approach/retreat pre-point search ladder, in metres."""
    min_distance: float = Field(gt=0)
    max_distance: float = Field(gt=0)
    step: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_ladder(self):
        _finite(self.min_distance, "min_distance")
        _finite(self.max_distance, "max_distance")
        _finite(self.step, "step")
        if self.min_distance > self.max_distance:
            raise ValueError("atomic_command_invalid: search min_distance exceeds max_distance")
        return self


class ApproachParameters(StrictModel):
    """Omitted ``search`` means the control ladder 0.10 down to 0.02 m by 5 mm."""
    target: SceneId
    search: SearchParameters | None = None


class PickParameters(StrictModel):
    target: SceneId
    hold_force: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_force(self):
        if self.hold_force is not None:
            _finite(self.hold_force, "hold_force")
        return self


class LiftUpParameters(StrictModel):
    """No target: the lift starts at the current end-effector pose."""
    distance: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_distance(self):
        if self.distance is not None:
            _finite(self.distance, "distance")
        return self


class RetreatParameters(StrictModel):
    """Omitted ``search`` means the control ladder 0.10 down to 0.03 m by 5 mm."""
    target: SceneId
    search: SearchParameters | None = None
    pose_axis: PoseAxis | None = None


class MoveToParameters(StrictModel):
    target: Union[SceneId, NamedTarget]
    planning_method: PlanningMethod | None = None
    relation: MoveRelation | None = None
    distance_m: float | None = Field(default=None, ge=0)
    keep_end_effector_orientation: bool | None = None

    @model_validator(mode="after")
    def validate_offset(self):
        if self.distance_m is not None:
            _finite(self.distance_m, "distance_m")
        if self.distance_m is not None and self.relation is None:
            raise ValueError("atomic_command_invalid: distance_m requires relation")
        if self.target == "end_effector" and self.planning_method not in (None, "linear"):
            raise ValueError("atomic_command_invalid: end_effector moves require a linear path")
        return self


class PutParameters(StrictModel):
    """Omitted ``relation`` means the destination's own internal placement.

    ``above`` and ``below`` are the two relations the control resolves without
    perception: it offsets the destination's own box along world Z and releases
    the object in the air, so they need no visible support surface.
    """
    target: SceneId
    relation: PutRelation | None = None
    distance_m: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_relative_placement(self):
        if self.distance_m is not None:
            _finite(self.distance_m, "distance_m")
            if self.relation in (None, "at"):
                raise ValueError("atomic_command_invalid: distance_m requires a relative direction")
        return self


class ReleaseParameters(StrictModel):
    """Open the gripper where it stands.

    The target is the scene id of the object being let go; the control performs
    no motion and no support check -- it unbinds, opens and lets the physics
    settle, which is what an in-plane landing needs.
    """
    target: SceneId


class PullPushParameters(StrictModel):
    """A straight pull/push from the measured end-effector pose; the drawer is
    already held, so there is no ``target``, and the control opens the gripper
    again when the stroke finishes."""
    distance: float = Field(gt=0)
    frame: MotionFrame | None = None
    direction: list[float] | None = None

    @model_validator(mode="after")
    def validate_stroke(self):
        _finite(self.distance, "distance")
        if self.direction is not None:
            if len(self.direction) != 3 or not all(math.isfinite(value) for value in self.direction):
                raise ValueError("atomic_command_invalid: direction must be three finite numbers")
            if not any(self.direction):
                raise ValueError("atomic_command_invalid: direction must be non-zero")
        return self


PARAMETER_TYPES = {
    AtomicSkillName.APPROACH: ApproachParameters,
    AtomicSkillName.PICK: PickParameters,
    AtomicSkillName.LIFT_UP: LiftUpParameters,
    AtomicSkillName.RETREAT: RetreatParameters,
    AtomicSkillName.MOVE_TO: MoveToParameters,
    AtomicSkillName.PUT: PutParameters,
    AtomicSkillName.PULL: PullPushParameters,
    AtomicSkillName.PUSH: PullPushParameters,
    AtomicSkillName.RELEASE: ReleaseParameters,
}


class AtomicCommand(StrictModel):
    command_id: str = Field(min_length=1)
    skill_name: AtomicSkillName
    parameters: Union[ApproachParameters, PickParameters, LiftUpParameters, RetreatParameters,
                      MoveToParameters, PutParameters, PullPushParameters, ReleaseParameters]

    @model_validator(mode="before")
    @classmethod
    def typed_parameters(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        try:
            kind = AtomicSkillName(data.get("skill_name"))
        except ValueError:
            # An invented skill name must surface as the field's own enum error;
            # the stage maps that code to "the model used an unknown skill".
            return data
        params = data.get("parameters", {})
        if isinstance(params, BaseModel):
            params = params.model_dump(mode="json", exclude_none=True)
        data["parameters"] = PARAMETER_TYPES[kind].model_validate(params)
        return data


class AtomicCommandsFile(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    request_id: str = Field(min_length=1)
    scene_id: SceneId
    scene_version: int = Field(strict=True, ge=0)
    commands: list[AtomicCommand] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_command_ids(self):
        identifiers = [command.command_id for command in self.commands]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("atomic_command_invalid: command_id values must be unique")
        return self


class AtomicCommandDraft(StrictModel):
    """The planning round answers with only the command list.

    ``request_id``, ``scene_id`` and ``scene_version`` belong to Python: making the
    model echo them adds a hallucination surface without adding information.
    """
    commands: list[AtomicCommand] = Field(min_length=1)


def canonical_atomic_commands(commands: AtomicCommandsFile) -> dict[str, Any]:
    """The sole wire representation of the atomic dialect."""
    payload = commands.model_dump(mode="json", exclude_none=True)
    AtomicCommandsFile.model_validate(payload)
    json.dumps(payload, allow_nan=False)
    Draft202012Validator(AtomicCommandsFile.model_json_schema()).validate(payload)
    return payload
