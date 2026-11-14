"""Strict wire models for the isolated failure-context.v1 recovery round.

This module deliberately has no command or permission fields.  The recovery
model may amend a user request, but it cannot authorize execution or bypass a
scene/lease validator.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FailureContextHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str
    user: str
    assistant: str | None = None
    outcome: str
    error_code: str | None = None
    effective_instruction: str | None = None
    effects: dict[str, Any] = Field(default_factory=dict)


class FailureContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["failure_context.v1"] = "failure_context.v1"
    current_user_text: str = Field(min_length=1, max_length=20000)
    root_failure_turn_id: str = Field(min_length=1)
    history: list[FailureContextHistoryItem] = Field(default_factory=list, max_length=5)
    latest_task_draft: dict[str, Any] = Field(default_factory=dict)
    step_ledger: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_slots: list[str] = Field(default_factory=list)
    current_scene_context: dict[str, Any] = Field(default_factory=dict)
    catalog_revision: str | None = None
    workspace_semantics: str = "desktop_only"
    policy_summary: dict[str, Any] = Field(default_factory=dict)
    allowed_recovery_actions: list[Literal["continue_task", "revise_task", "new_task", "ask_user", "cancel_chain"]] = Field(default_factory=lambda: ["ask_user", "cancel_chain"])


class FailureContextAmendment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_role: str = Field(min_length=1)
    field: Literal["selection", "quantity", "goal", "distance", "operation", "target", "reference", "color", "placement"]
    value: Any
    evidence: dict[str, Any] = Field(default_factory=dict)


class FailureContextDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["failure_context.v1"] = "failure_context.v1"
    decision: Literal["continue_task", "revise_task", "new_task", "ask_user", "cancel_chain"]
    source_turn_id: str = Field(min_length=1)
    scope: Literal["failed_step", "remaining_steps", "new_task"] = "failed_step"
    target_step_id: str | None = None
    resolved_instruction: str | None = None
    amendments: list[FailureContextAmendment] = Field(default_factory=list)
    question: str | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def valid_shape(self):
        if self.decision == "ask_user":
            if not self.question or self.resolved_instruction is not None or self.amendments:
                raise ValueError("failure_context_ask_user_payload_invalid")
        elif self.decision in {"continue_task", "revise_task", "new_task"}:
            if not self.resolved_instruction:
                raise ValueError("failure_context_resolved_instruction_required")
            if self.question is not None:
                raise ValueError("failure_context_question_forbidden")
        else:
            if self.resolved_instruction is not None or self.amendments or self.question is not None:
                raise ValueError("failure_context_cancel_payload_invalid")
        if self.source_turn_id == "":
            raise ValueError("failure_context_source_turn_invalid")
        return self


def failure_context_wire_schema() -> dict[str, Any]:
    return FailureContextDecision.model_json_schema()
