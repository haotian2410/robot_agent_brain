"""Durable user-turn and bounded failure-chain memory.

This module deliberately contains no execution logic.  It is the audit and
recovery state shared by the Web outer request and the normal Brain pipeline.
Model output can only propose changes; callers must validate those changes
before storing or executing them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FailureChainState(StrEnum):
    WAITING_USER = "waiting_user"
    BLOCKED_ENVIRONMENT = "blocked_environment"
    BLOCKED_SYSTEM = "blocked_system"
    BLOCKED_RECONCILIATION = "blocked_reconciliation"
    RESOLVING = "resolving"
    RESOLVED = "resolved"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class EffectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_effect: Literal["none_confirmed", "committed", "unknown"] = "unknown"
    execution_effect: Literal[
        "not_started", "simulation_discarded", "partial_confirmed",
        "completed", "unknown"
    ] = "unknown"
    execution_environment: Literal["isolated_simulation", "physical_robot", "unknown"] = "unknown"
    holding_state: Literal["empty_confirmed", "holding_confirmed", "unknown"] = "unknown"
    publication_state: Literal["none", "published", "failed", "unknown"] = "unknown"
    lease_state: str | None = None
    transaction_id: str | None = None
    control_run_id: str | None = None
    evidence_source: list[str] = Field(default_factory=list)


class SemanticDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_request_id: str
    validity: Literal["validated_turn", "partial_semantics", "unparsed"] = "unparsed"
    canonical_turn: dict[str, Any] | None = None
    known_fields: list[str] = Field(default_factory=list)
    unresolved_slots: list[str] = Field(default_factory=list)
    confirmed_bindings: list[dict[str, Any]] = Field(default_factory=list)
    candidate_evidence: list[dict[str, Any]] = Field(default_factory=list)
    field_provenance: list[dict[str, Any]] = Field(default_factory=list)
    execution_authority: Literal["none"] = "none"


class RecoveryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_current_user_text: str
    source_turn_ids: list[str] = Field(default_factory=list)
    base_instruction: str | None = None
    effective_instruction: str | None = None
    accepted_amendments: list[dict[str, Any]] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)
    superseded_fields: dict[str, Any] = Field(default_factory=dict)
    scene_basis_authorization: str | None = None
    scope: Literal["failed_step", "remaining_steps", "new_task"] = "failed_step"
    base_instruction_digest: str | None = None
    draft_digest: str | None = None
    recovery_decision_digest: str | None = None


class StepLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    original_step_index: int
    task_revision: int = 0
    instruction: str
    route_hint: str | None = None
    status: Literal[
        "planned", "processing", "committed", "executed_confirmed",
        "plan_ready_unexecuted", "clarification", "rejected", "unknown", "not_run"
    ] = "planned"
    request_ids: list[str] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    scene_before: dict[str, Any] | None = None
    scene_after: dict[str, Any] | None = None
    receipts: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_effects: list[str] = Field(default_factory=list)
    holding_state: str | None = None
    semantic_draft_ref: str | None = None
    canonical_turn: dict[str, Any] | None = None
    understanding_evidence: dict[str, Any] | None = None
    control_run_ids: list[str] = Field(default_factory=list)


class SelectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_role: str
    chosen_ids: list[int]
    candidate_ids: list[int]
    decision_key: str
    policy: Literal["auto", "ask"] = "auto"
    color_evidence_status: Literal["verified", "unverifiable_fallback", "not_applicable"] = "not_applicable"
    color_verified: bool | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str
    session_id: str
    sequence: int = Field(ge=1)
    client_request_id: str | None = None
    web_task_id: str | None = None
    raw_user_text: str
    effective_instruction: str | None = None
    assistant_final_text: str = ""
    final_outcome: str
    final_error_code: str | None = None
    final_stage: str | None = None
    child_request_ids: list[str] = Field(default_factory=list)
    scene_before: dict[str, Any] | None = None
    scene_after: dict[str, Any] | None = None
    scene_commit_status: str | None = None
    execution_status: str | None = None
    executed: bool = False
    publication_status: str | None = None
    lease_status: str | None = None
    effect_evidence: EffectEvidence = Field(default_factory=EffectEvidence)
    context_chain_id: str | None = None
    root_failure_turn_id: str | None = None
    auto_selection_decisions: list[SelectionDecision] = Field(default_factory=list)
    finalization_revision: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finalized_at: str | None = None
    recovery_evidence: RecoveryEvidence | None = None
    step_ledger: list[StepLedgerEntry] = Field(default_factory=list)


class FailureChain(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chain_id: str
    root_failure_turn_id: str
    root_instruction: str
    root_task_id: str | None = None
    state: FailureChainState = FailureChainState.WAITING_USER
    failed_user_turn_ids: list[str] = Field(default_factory=list, max_length=5)
    last_attempt_turn_id: str | None = None
    last_failure_request_id: str | None = None
    latest_question: str | None = None
    accepted_task_revision: int = 0
    semantic_draft: SemanticDraft | None = None
    step_ledger: list[StepLedgerEntry] = Field(default_factory=list)
    current_failed_step_id: str | None = None
    remaining_step_ids: list[str] = Field(default_factory=list)
    scene_binding: dict[str, Any] | None = None
    catalog_revision: str | None = None
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    selection_decisions: list[SelectionDecision] = Field(default_factory=list)
    constraint_revision: int = 0
    lifecycle_revision: int = 0
    platform_signature: str | None = None
    config_fingerprint: str | None = None

    def register_failed_turn(self, turn_id: str) -> int:
        if turn_id not in self.failed_user_turn_ids:
            if len(self.failed_user_turn_ids) >= 5:
                self.state = FailureChainState.EXHAUSTED
            else:
                self.failed_user_turn_ids.append(turn_id)
                self.lifecycle_revision += 1
                if len(self.failed_user_turn_ids) >= 5:
                    self.state = FailureChainState.EXHAUSTED
        return len(self.failed_user_turn_ids)

    @property
    def failed_user_turn_count(self) -> int:
        return len(self.failed_user_turn_ids)


class ConversationMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1.0"] = "1.0"
    recent_turns: list[ConversationTurn] = Field(default_factory=list)
    active_failure_chain: FailureChain | None = None
    archived_turn_ids: list[str] = Field(default_factory=list)
    max_recent_turns: int = Field(default=5, ge=1, le=100)

    def upsert_turn(self, turn: ConversationTurn) -> None:
        for index, old in enumerate(self.recent_turns):
            if old.turn_id == turn.turn_id:
                self.recent_turns[index] = turn
                return
        self.recent_turns.append(turn)
        if len(self.recent_turns) > self.max_recent_turns:
            removed = self.recent_turns[:-self.max_recent_turns]
            self.archived_turn_ids.extend(item.turn_id for item in removed)
        self.recent_turns = self.recent_turns[-self.max_recent_turns:]

    def revise_turn(self, turn_id: str, **changes: Any) -> ConversationTurn:
        """Apply late authoritative facts without creating a user turn.

        Gateway/Control callbacks may arrive after the outer task was marked
        unknown.  They revise the existing audit row and never increment a
        failure chain counter.
        """
        for index, old in enumerate(self.recent_turns):
            if old.turn_id != turn_id:
                continue
            updated = old.model_copy(update={**changes,
                                             "finalization_revision": old.finalization_revision + 1,
                                             "finalized_at": datetime.now(timezone.utc).isoformat()})
            self.recent_turns[index] = updated
            return updated
        raise ValueError("conversation_turn_not_found")

    def begin_failure(self, turn: ConversationTurn, *, question: str | None = None,
                      draft: SemanticDraft | None = None, policy: dict[str, Any] | None = None) -> FailureChain:
        chain = self.active_failure_chain
        if chain is None or chain.state in {
            FailureChainState.RESOLVED, FailureChainState.CANCELLED,
            FailureChainState.EXHAUSTED, FailureChainState.SUPERSEDED,
        }:
            chain = FailureChain(
                chain_id=f"chain-{turn.turn_id}",
                root_failure_turn_id=turn.turn_id,
                root_instruction=turn.raw_user_text,
                policy_snapshot=dict(policy or {}),
                semantic_draft=draft,
            )
            self.active_failure_chain = chain
        chain.latest_question = question
        chain.last_attempt_turn_id = turn.turn_id
        chain.register_failed_turn(turn.turn_id)
        turn.context_chain_id = chain.chain_id
        turn.root_failure_turn_id = chain.root_failure_turn_id
        self.upsert_turn(turn)
        return chain
