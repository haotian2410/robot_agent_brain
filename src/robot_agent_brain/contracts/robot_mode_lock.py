"""Persistable mode decision at accepted robot planning or explicit setup."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RobotModeLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["single", "dual"]
    profile_id: str = Field(min_length=1)
    locked: bool = Field(default=False, strict=True)
    locked_at_turn: int | None = Field(default=None, ge=1, strict=True)
    source: Literal["scene", "first_turn", "default"]
    setup_revision: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_boundary(self):
        if self.locked != (self.locked_at_turn is not None):
            raise ValueError("robot_mode_lock_boundary_invalid")
        if not self.profile_id.strip() or self.profile_id != self.profile_id.strip():
            raise ValueError("robot_mode_lock_profile_invalid")
        return self

    @property
    def prompt_route(self):
        return "dual_atomic" if self.mode == "dual" else "single_atomic"

    def check_request(self, request):
        if request is None or not self.locked:
            return
        if request.mode != self.mode:
            raise ValueError("robot_mode_locked")
        if request.profile_id is not None and request.profile_id != self.profile_id:
            raise ValueError("robot_setup_change_after_first_turn_unsupported")

    def accept(self, turn_index):
        if type(turn_index) is not int or turn_index < 1:
            raise ValueError("robot_mode_lock_turn_invalid")
        if self.locked:
            return self
        return type(self).model_validate({**self.model_dump(), "locked": True,
                                         "locked_at_turn": turn_index})

    def check_setup(self, setup, revision):
        if setup is None:
            if self.mode == "single" and self.profile_id == "default_single" and self.setup_revision == revision:
                return
            raise ValueError("robot_mode_lock_setup_mismatch")
        if (setup.mode, setup.profile_id, revision) != (
                self.mode, self.profile_id, self.setup_revision):
            raise ValueError("robot_mode_lock_setup_mismatch")
