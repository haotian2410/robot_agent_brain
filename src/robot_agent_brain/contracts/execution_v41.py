"""Proposed Brain-side 4.1 execution boundary; not a production Control API.

No transport or public feedback endpoint is installed by these models.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator, field_serializer
from .commands_sequence_v41 import CommandsFileV41, canonical_commands_v41
from .robot_setup import RobotSetup, RobotRuntimeState
from .scene import SceneConfig


class ExecutionEnvelopeV41(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boundary_version: Literal["brain.execution.v41.proposal.1"]
    session_id: str = Field(min_length=1)
    commands: CommandsFileV41
    scene: SceneConfig
    setup: RobotSetup
    setup_revision: int = Field(strict=True, ge=1)
    skill_contract_revision: str = Field(min_length=1)
    runtime: RobotRuntimeState

    @field_validator("scene", mode="before")
    @classmethod
    def lossless_scene(cls, value):
        from .scene import parse_scene_document
        return parse_scene_document(value, uint32=False).view if isinstance(value, dict) else value

    @field_serializer("scene")
    def scene_document(self, value):
        return value.raw_document()

    @model_validator(mode="after")
    def bound_inputs(self):
        from ..web.protocol import digest
        canonical_commands_v41(self.commands)
        if (self.commands.scene_id, self.commands.scene_version, self.commands.scene_digest) != (
                self.scene.scene_id, self.scene.scene_version, digest(self.scene)):
            raise ValueError("execution_v41_scene_binding_mismatch")
        if (self.setup.mode != "dual" or self.commands.robot_setup_revision != self.setup_revision
                or self.commands.skill_contract_revision != self.skill_contract_revision):
            raise ValueError("execution_v41_revision_mismatch")
        self.runtime.require_idle(self.setup)
        ids = {obj.object_id_in_scene for obj in self.scene.objects}
        if not {arm.robot_object_id for arm in self.setup.arms.values()} <= ids:
            raise ValueError("execution_v41_robot_binding_missing")
        return self


class CommandResultV41(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    arm: Literal["left", "right"]
    status: Literal["success", "failed", "not_run", "unknown"]


class ExecutionFeedbackV41(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boundary_version: Literal["brain.execution.v41.proposal.1"]
    session_id: str
    request_id: str
    input_scene_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    setup_revision: int = Field(strict=True, ge=1)
    skill_contract_revision: str
    status: Literal["success", "failed", "partial", "unknown"]
    commands: list[CommandResultV41]
    runtime: RobotRuntimeState | None = None
    final_scene: SceneConfig | None = None
    effect_evidence: Literal["verified_final_state", "verified_no_effect", "unknown"]

    @field_validator("final_scene", mode="before")
    @classmethod
    def lossless_scene(cls, value):
        from .scene import parse_scene_document
        return parse_scene_document(value, uint32=False).view if isinstance(value, dict) else value

    @field_serializer("final_scene")
    def scene_document(self, value):
        return value.raw_document() if value is not None else None

    def validate_against(self, envelope: ExecutionEnvelopeV41):
        expected = envelope.commands
        if (self.session_id, self.request_id, self.input_scene_digest, self.setup_revision,
                self.skill_contract_revision) != (envelope.session_id, expected.request_id,
                expected.scene_digest, expected.robot_setup_revision, expected.skill_contract_revision):
            raise ValueError("execution_v41_feedback_binding_mismatch")
        by_id = {row.command_id: row for row in self.commands}
        if len(by_id) != len(self.commands) or set(by_id) != {c.command_id for c in expected.commands}:
            raise ValueError("execution_v41_feedback_coverage_invalid")
        for command in expected.commands:
            row = by_id[command.command_id]
            if row.arm != command.arm:
                raise ValueError("execution_v41_feedback_arm_mismatch")
            if row.status == "success" and any(by_id[key].status != "success" for key in command.depends_on):
                raise ValueError("execution_v41_feedback_dependency_failed")
        if self.status == "success" and (any(row.status != "success" for row in self.commands)
                or self.effect_evidence != "verified_final_state"
                or self.final_scene is None or self.runtime is None):
            raise ValueError("execution_v41_success_unverified")
        if self.runtime is not None:
            if set(self.runtime.arms) != set(envelope.setup.arms):
                raise ValueError("execution_v41_feedback_runtime_incomplete")
            if self.status == "success" and any(not arm.state_known for arm in self.runtime.arms.values()):
                raise ValueError("execution_v41_success_unverified")
        if self.final_scene is not None:
            if (self.final_scene.scene_id != envelope.scene.scene_id
                    or self.final_scene.scene_version < envelope.scene.scene_version):
                raise ValueError("execution_v41_final_scene_stale")
        if self.effect_evidence == "verified_no_effect" and any(row.status == "success" for row in self.commands):
            raise ValueError("execution_v41_no_effect_contradiction")
        return self
