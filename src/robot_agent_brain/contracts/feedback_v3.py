"""Final Control feedback for staged execution; absent arms remain unknown."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .robot_setup import ArmRuntimeState
from .scene import SceneId


class DualActionFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    command_id: str
    arm: Literal["left", "right"]
    status: Literal["success", "failed"]


class ExecutionRecoveryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    scene_id: SceneId
    base_scene_version: int = Field(strict=True, ge=0)
    minimum_scene_version: int = Field(strict=True, ge=0)
    robot_setup_revision: int = Field(strict=True, ge=1)
    feedback_status: Literal["success", "failed", "partial"]
    source: Literal["external", "simulated"]


class ExecutionFeedbackV3(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["3.0"] = "3.0"
    request_id: str
    scene_id: SceneId
    scene_version: int = Field(strict=True, ge=0)
    robot_setup_revision: int = Field(strict=True, ge=1)
    status: Literal["success", "failed", "partial"]
    actions: list[DualActionFeedback]
    arms: dict[Literal["left", "right"], ArmRuntimeState] = Field(default_factory=dict)

    def validate_against(self, plan, initial_state=None):
        if (self.request_id, self.scene_id, self.scene_version, self.robot_setup_revision) != (
                plan.request_id, plan.scene_id, plan.scene_version, plan.robot_setup_revision):
            raise ValueError("execution_feedback_context_mismatch")
        expected = {command.command_id: (i, stage.step_id, side)
                    for i, stage in enumerate(plan.steps) for side in ("left", "right")
                    if (command := getattr(stage.arms, side)) is not None}
        actual = {}
        for action in self.actions:
            if action.command_id in actual or action.command_id not in expected:
                raise ValueError("execution_feedback_command_mismatch")
            _, step, side = expected[action.command_id]
            if (action.step_id, action.arm) != (step, side):
                raise ValueError("execution_feedback_arm_or_stage_mismatch")
            actual[action.command_id] = action.status
        highest = max((expected[key][0] for key in actual), default=-1)
        for identifier, (stage, _, _) in expected.items():
            if stage < highest and actual.get(identifier) != "success":
                raise ValueError("execution_feedback_barrier_violation")
        if self.status == "success" and (set(actual) != set(expected) or any(v != "success" for v in actual.values())
                                         or set(self.arms) != {"left", "right"} or any(not a.state_known for a in self.arms.values())):
            raise ValueError("execution_feedback_incomplete_success")
        complete_success = (set(actual) == set(expected) and all(v == "success" for v in actual.values())
                            and set(self.arms) == {"left", "right"} and all(a.state_known for a in self.arms.values()))
        if ((self.status == "failed" and actual and "failed" not in actual.values())
                or (self.status == "partial" and ("success" not in actual.values() or complete_success))):
            raise ValueError("execution_feedback_status_mismatch")
        held = [a.holding_object for a in self.arms.values() if a.holding_object is not None]
        if len(held) != len(set(held)):
            raise ValueError("execution_feedback_shared_ownership_unsupported")
        if self.status == "success" and initial_state is not None:
            predicted = {side: arm.holding_object for side, arm in initial_state.arms.items()}
            for stage in plan.steps:
                for side in ("left", "right"):
                    command = getattr(stage.arms, side)
                    if command is not None and command.skill_name == "grasp":
                        predicted[side] = command.parameters.target
                    elif command is not None and command.skill_name == "release":
                        predicted[side] = None
            if any(self.arms[side].holding_object != value for side, value in predicted.items()):
                raise ValueError("execution_feedback_success_holding_mismatch")
