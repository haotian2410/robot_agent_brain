"""Scene-bound visual arm identity; image-left is not a robot arm label."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.camera import CameraFrame


class BoundArmOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1)
    source: int = Field(ge=0)
    destination: int | None = Field(default=None, ge=0)
    locked_arm: Literal["left", "right"] | None = None


class ArmAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: int = Field(ge=0)
    scene_version: int = Field(ge=0)
    scene_sub_version: int = Field(ge=0)
    scene_digest: str = Field(min_length=1)
    robot_mode: Literal["dual"] = "dual"
    arm_labels: dict[Literal["left", "right"], int]
    operations: list[BoundArmOperation] = Field(min_length=1)
    initial_held_objects: dict[Literal["left", "right"], int | None]
    both_required: bool = False
    frame: CameraFrame = Field(exclude=True)

    @model_validator(mode="after")
    def evidence_identity(self):
        if (self.frame.scene_id, self.frame.scene_version, self.frame.scene_sub_version) != (
                self.scene_id, self.scene_version, self.scene_sub_version):
            raise ValueError("arm_assignment_frame_scene_mismatch")
        if set(self.arm_labels) != {"left", "right"} or len(set(self.arm_labels.values())) != 2:
            raise ValueError("arm_assignment_arm_labels_invalid")
        if set(self.initial_held_objects) != {"left", "right"}:
            raise ValueError("arm_assignment_runtime_missing")
        ids = [box.scene_object_id for box in self.frame.instance_boxes]
        required = set(self.arm_labels.values()) | {op.source for op in self.operations}
        if not self.frame.rgb or len(ids) != len(set(ids)) or not required <= set(ids):
            raise ValueError("arm_assignment_visual_evidence_missing")
        operation_ids = [op.operation_id for op in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("arm_assignment_operation_coverage_invalid")
        return self
