"""Logical arm assignment contract; no IK or collision decisions live here."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArmAssignmentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1)
    arm: Literal["single", "left", "right"] = "single"
    depends_on: list[str] = Field(default_factory=list)
    resource_groups: list[str] = Field(default_factory=list)


class ArmAssignmentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["single_arm", "dual_arm"]
    steps: list[ArmAssignmentStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self):
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("arm_assignment_duplicate_step")
        known = set(ids)
        if any(dep not in known for step in self.steps for dep in step.depends_on):
            raise ValueError("arm_assignment_unknown_dependency")
        if self.mode == "single_arm" and any(step.arm != "single" for step in self.steps):
            raise ValueError("arm_assignment_single_arm_mismatch")
        return self


def validate_arm_assignment(plan: ArmAssignmentPlan) -> ArmAssignmentPlan:
    """Return the validated logical plan without selecting robot geometry."""
    return ArmAssignmentPlan.model_validate(plan)


class OperationArmAssignment(BaseModel):
    """Model-facing assignment contains no scheduling or resource decisions."""
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1)
    arm: Literal["left", "right"]


class ArmAssignmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["assigned", "insufficient_evidence"]
    assignments: list[OperationArmAssignment] = Field(default_factory=list)
    arm_order: dict[Literal["left", "right"], list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent_output(self):
        if self.status == "insufficient_evidence":
            if self.assignments or self.arm_order:
                raise ValueError("arm_assignment_insufficient_evidence_with_assignments")
            return self
        ids = [item.operation_id for item in self.assignments]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("arm_assignment_operation_coverage_invalid")
        for arm in ("left", "right"):
            ordered = self.arm_order.get(arm, [])
            expected = {item.operation_id for item in self.assignments if item.arm == arm}
            if len(ordered) != len(set(ordered)) or set(ordered) != expected:
                raise ValueError("arm_assignment_order_coverage_invalid")
        return self


def validate_assignment_output(output: ArmAssignmentOutput, *, operation_ids,
                               locked_arms=None, both_required=False,
                               same_arm_groups=(), ordered_operations=()):
    """Validate model output against Python-owned bindings and constraints."""
    output = ArmAssignmentOutput.model_validate(output)
    if output.status != "assigned":
        raise ValueError("arm_assignment_insufficient_evidence")
    requested = list(operation_ids)
    assignments = {item.operation_id: item.arm for item in output.assignments}
    if len(requested) != len(set(requested)) or set(requested) != set(assignments):
        raise ValueError("arm_assignment_operation_coverage_invalid")
    for operation_id, arm in (locked_arms or {}).items():
        if assignments.get(operation_id) != arm:
            raise ValueError("arm_assignment_locked_arm_changed")
    if both_required and set(assignments.values()) != {"left", "right"}:
        raise ValueError("arm_assignment_both_required")
    for group in same_arm_groups:
        if any(item not in assignments for item in group) or len({assignments[item] for item in group}) > 1:
            raise ValueError("arm_assignment_continuity_changed")
    for arm in ("left", "right"):
        expected = [item for item in ordered_operations if assignments.get(item) == arm]
        actual = [item for item in output.arm_order.get(arm, []) if item in expected]
        if actual != expected:
            raise ValueError("arm_assignment_explicit_order_changed")
    return output
