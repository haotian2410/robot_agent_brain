"""Policy checks around failure-context.v1 decisions.

The model is advisory.  This guard is the authority that decides whether a
recovery answer can be attached to the original request.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from ..models.failure_context import FailureContextDecision


class FailureClass(StrEnum):
    USER_CLARIFICATION = "user_clarification"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    SYSTEM_BLOCKED = "system_blocked"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    UNKNOWN = "unknown"


def classify_failure(result: dict[str, Any] | None, *, uncertain: bool = False) -> FailureClass:
    result = result or {}
    code = str((result.get("error") or {}).get("code") or "")
    if uncertain or code.startswith(("gateway_", "lease_", "recovery_", "session_reconciliation")):
        return FailureClass.RECONCILIATION_REQUIRED
    if result.get("outcome") == "clarification_required" or code in {
        "grounding_ambiguous", "scene_reference_ambiguous", "asset_choice_missing",
    }:
        return FailureClass.USER_CLARIFICATION
    if code in {"provider_transport_error", "provider_timeout", "control_unavailable"}:
        return FailureClass.ENVIRONMENT_BLOCKED
    if code.startswith(("provider_", "semantic_", "task_understanding_", "scene_edit_runtime")):
        return FailureClass.SYSTEM_BLOCKED
    return FailureClass.UNKNOWN


def validate_recovery_decision(decision: FailureContextDecision, *, root_failure_turn_id: str,
                               known_turn_ids: set[str], completed_step_ids: set[str] | None = None,
                               allowed_actions: set[str] | None = None) -> FailureContextDecision:
    """Reject fabricated or out-of-chain amendments before reattaching them."""
    if decision.source_turn_id not in known_turn_ids:
        raise ValueError("failure_context_source_turn_unknown")
    if root_failure_turn_id not in known_turn_ids:
        raise ValueError("failure_context_root_turn_unknown")
    if allowed_actions is not None and decision.decision not in allowed_actions:
        raise ValueError("failure_context_action_not_allowed")
    completed_step_ids = completed_step_ids or set()
    if decision.target_step_id in completed_step_ids:
        raise ValueError("failure_context_completed_step_immutable")
    for amendment in decision.amendments:
        # The recovery round can amend interpretation, never authority or identity.
        if amendment.field in {"selection", "target", "reference"} and amendment.evidence.get("source") in {None, "model_guess"}:
            raise ValueError("failure_context_binding_requires_evidence")
        if amendment.subject_role.strip() == "":
            raise ValueError("failure_context_subject_invalid")
    return decision
