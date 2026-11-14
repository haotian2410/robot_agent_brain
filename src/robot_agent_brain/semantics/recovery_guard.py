"""Policy checks around failure-context.v1 decisions.

The model is advisory.  This guard is the authority that decides whether a
recovery answer can be attached to the original request.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from ..models.failure_context import FailureContextDecision

_FORBIDDEN_RECOVERY_FIELDS = {
    "id", "object_id", "scene_id", "platform", "robot", "lease", "permission",
    "commands", "execution", "control", "scene_basis", "original_snapshot",
}


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


def validate_recovery_scope(decision: FailureContextDecision, *, root_instruction: str,
                            latest_task_draft: dict[str, Any] | None = None,
                            current_user_text: str | None = None) -> FailureContextDecision:
    """Keep the read-only R round from changing the authority of U.

    ``resolved_instruction`` is only fed back through the ordinary U parser;
    this guard rejects scope/field attempts that would otherwise look like an
    instruction to bypass identity, platform, lease or execution validation.
    The original text and draft are retained as evidence for the caller.
    """
    if not root_instruction.strip():
        raise ValueError("failure_context_root_instruction_missing")
    if decision.scope == "new_task" and decision.decision != "new_task":
        raise ValueError("failure_context_scope_new_task_mismatch")
    if decision.decision == "new_task" and decision.scope != "new_task":
        raise ValueError("failure_context_new_task_scope_required")
    if current_user_text is not None and decision.resolved_instruction:
        original_markers = ("原始场景", "原场景", "original scene", "original")
        resolved_original = any(marker in decision.resolved_instruction.lower() for marker in original_markers)
        user_original = any(marker in current_user_text.lower() for marker in original_markers)
        if resolved_original and not user_original:
            raise ValueError("failure_context_scene_basis_drift")
    for amendment in decision.amendments:
        field = amendment.field.strip().lower()
        if field in _FORBIDDEN_RECOVERY_FIELDS:
            raise ValueError("failure_context_authority_field_forbidden: " + field)
        # A recovery amendment must either fill a slot recorded by U or carry
        # explicit user-turn evidence.  Model guesses are never sufficient.
        evidence = amendment.evidence or {}
        unresolved = set((latest_task_draft or {}).get("unresolved_slots") or [])
        if unresolved and field not in unresolved and evidence.get("source") in {None, "model_guess"}:
            raise ValueError("failure_context_amendment_without_user_evidence: " + field)
    return decision
