"""Explicit deployment bindings, never inferred from image position or joints."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .scene import SceneId

ArmName = Literal["single", "left", "right"]


class RobotSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["single", "dual"]
    profile_id: str | None = Field(default=None, min_length=1, pattern=r"\S")


class ArmBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_object_id: SceneId
    planning_group: str = Field(min_length=1, pattern=r"\S")
    end_effector: str = Field(min_length=1, pattern=r"\S")
    gripper: str = Field(min_length=1, pattern=r"\S")


class RobotSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["single", "dual"]
    profile_id: str = Field(min_length=1, pattern=r"\S")
    arms: dict[ArmName, ArmBinding]

    @model_validator(mode="after")
    def bindings_match_mode(self):
        expected = {"single"} if self.mode == "single" else {"left", "right"}
        if set(self.arms) != expected:
            raise ValueError("robot_setup_arm_mapping_invalid")
        for resource in ("planning_group", "end_effector", "gripper"):
            bindings = [(arm.robot_object_id, getattr(arm, resource)) for arm in self.arms.values()]
            if len(set(bindings)) != len(bindings):
                raise ValueError("robot_setup_shared_resource_requires_contract: " + resource)
        return self


class ArmRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_known: bool = Field(strict=True)
    holding_object: SceneId | None = None


class RobotRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arms: dict[ArmName, ArmRuntimeState]

    def require_idle(self, setup: RobotSetup):
        if set(self.arms) != set(setup.arms):
            raise ValueError("robot_runtime_arm_mapping_invalid")
        if any(not state.state_known for state in self.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        if any(state.holding_object is not None for state in self.arms.values()):
            raise ValueError("robot_runtime_holding_object")
