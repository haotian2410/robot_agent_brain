"""Deterministic, opt-in ambiguity handling for semantic selections."""
from __future__ import annotations

import hashlib
from typing import Any

from ..session.conversation_memory import SelectionDecision


class AmbiguityRequiresClarification(ValueError):
    code = "grounding_ambiguous"


class AmbiguityPolicy:
    def __init__(self, *, prefer_auto_resolve: bool = False):
        self.prefer_auto_resolve = bool(prefer_auto_resolve)

    @staticmethod
    def decision_key(session_id: str, logical_task_id: str, step_id: str,
                     role: str, revision: int, scene_digest: str) -> str:
        raw = "|".join(map(str, (session_id, logical_task_id, step_id, role, revision, scene_digest)))
        return hashlib.sha256(raw.encode()).hexdigest()

    def choose(self, candidates: list[Any], *, session_id: str, logical_task_id: str,
               step_id: str, role: str, revision: int, scene_digest: str,
               explicit: Any | None = None, destructive: bool = False,
               destination: bool = False, query: bool = False,
               evidence: dict[str, Any] | None = None) -> SelectionDecision:
        if explicit is not None:
            for item in candidates:
                if item == explicit or getattr(item, "object_id_in_scene", None) == explicit:
                    return SelectionDecision(entity_role=role, chosen_ids=[getattr(item, "object_id_in_scene", item)],
                                             candidate_ids=sorted((getattr(x, "object_id_in_scene", x) for x in candidates), key=str),
                                             decision_key=self.decision_key(session_id, logical_task_id, step_id, role, revision, scene_digest),
                                             policy="auto")
            raise AmbiguityRequiresClarification("explicit_selection_not_found")
        ids = sorted((getattr(item, "object_id_in_scene", item) for item in candidates), key=str)
        if len(ids) != 1:
            # Auto resolve is deliberately narrow: it never picks a destination,
            # destructive target, query member, or anything without a stable key.
            if not (self.prefer_auto_resolve and not (destructive or destination or query)
                    and len(ids) > 0 and all(isinstance(i, int) for i in ids)):
                raise AmbiguityRequiresClarification("grounding_ambiguous")
            index = int(hashlib.sha256(self.decision_key(session_id, logical_task_id, step_id, role, revision, scene_digest).encode()).hexdigest(), 16) % len(ids)
            chosen = ids[index]
            policy = "auto_deterministic"
        elif ids:
            chosen, policy = ids[0], "unique"
        else:
            raise AmbiguityRequiresClarification("grounding_missing")
        return SelectionDecision(entity_role=role, chosen_ids=[chosen], candidate_ids=ids,
                                 decision_key=self.decision_key(session_id, logical_task_id, step_id, role, revision, scene_digest),
                                 policy="auto" if policy != "ask" else "ask")
