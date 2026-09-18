"""
agents/retrieval.py - Arbiter Retrieval Agent

The RetrievalAgent's ONLY responsibility is evidence gathering.
It does not decide which policy wins — that is the Resolution Agent's job.

Pipeline:
  1. Build a rich query string from the question + context fields.
  2. Call policy_store.hybrid_retrieve() for semantic + structured evidence.
  3. Apply an additional supersession filter so obsolete versions don't
     crowd out current ones unless explicitly needed.
  4. Return all potentially relevant policies (may include superseded docs
     when they are still contextually important for history).
"""

from __future__ import annotations

import logging
import json
from datetime import date
from typing import List, Optional

from config import settings
from schemas import Policy, PolicyContext
from stores.policy_store import PolicyStore, _is_in_effect

logger = logging.getLogger(__name__)


class RetrievalAgent:
    """
    Evidence-gathering agent.

    Does NOT rank, score, or decide between policies — it collects the
    full evidence set that the Resolution Agent needs to reason over.

    Developer 1 (Retrieval / Data)
    """

    def __init__(self, policy_store: PolicyStore) -> None:
        self.policy_store = policy_store

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        question: str,
        context: PolicyContext,
        as_of_date: Optional[date] = None,
        n_results: int = 8,
    ) -> List[Policy]:
        """
        Retrieve all potentially relevant policies for a question + context.
        """
        effective_date = as_of_date or date.today()

        query = self._build_query_string(question, context)
        logger.info(
            "RetrievalAgent | question=%r as_of=%s n=%d",
            question[:120],
            effective_date,
            n_results,
        )

        # Hybrid retrieval (semantic + structured)
        try:
            candidates = self.policy_store.hybrid_retrieve(
                question=query,
                context=context,
                as_of_date=effective_date,
                n_results=n_results * 2,
            )
        except Exception as exc:
            msg = f"RetrievalAgent: policy_store.hybrid_retrieve() failed — {exc}"
            logger.exception(msg)
            raise RuntimeError(msg) from exc

        logger.info("RetrievalAgent | raw candidates=%d", len(candidates))

        # Supersession filter
        filtered = self._apply_supersession_filter(candidates, effective_date)

        result = filtered[:n_results]
        self._log_retrieved(result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_query_string(self, question: str, context: PolicyContext) -> str:
        """Enrich the question with context fields for semantic search."""
        parts = [question.strip()]
        if context.vendor:
            parts.append(f"vendor: {context.vendor}")
        if context.region:
            parts.append(f"region: {context.region}")
        if context.department:
            parts.append(f"department: {context.department}")
        if context.dataset:
            parts.append(f"dataset: {context.dataset}")
        if context.user_role:
            parts.append(f"role: {context.user_role}")
        if context.additional_context:
            # The request schema permits arbitrary structured context.  It
            # must be serialized before joining the retrieval query string.
            parts.append(
                "additional_context: "
                + json.dumps(context.additional_context, sort_keys=True, default=str)
            )
        return " | ".join(parts)

    def _apply_supersession_filter(
        self,
        policies: List[Policy],
        as_of_date: date,
    ) -> List[Policy]:
        """
        Filter to policies in effect on as_of_date.
        Keep both superseded and current versions so the Resolution Agent
        can reason about the supersession chain explicitly.
        """
        # Keep only active policies in effect on the given date
        in_scope: List[Policy] = [
            p for p in policies
            if p.is_active and _is_in_effect(p, as_of_date)
        ]

        if not in_scope:
            logger.warning(
                "RetrievalAgent | date filter removed ALL candidates "
                "(as_of=%s). Returning all active policies.",
                as_of_date,
            )
            in_scope = [p for p in policies if p.is_active]

        # Re-order: non-superseded first
        supersession_map = self.policy_store.get_supersession_map(in_scope)
        superseded_ids = set(supersession_map.keys())

        current = [p for p in in_scope if p.policy_id not in superseded_ids]
        superseded = [p for p in in_scope if p.policy_id in superseded_ids]

        ordered = current + superseded
        logger.debug(
            "RetrievalAgent | in_scope=%d current=%d superseded=%d",
            len(in_scope), len(current), len(superseded),
        )
        return ordered

    def _log_retrieved(self, policies: List[Policy]) -> None:
        if not policies:
            logger.warning("RetrievalAgent | No policies retrieved")
            return
        for i, p in enumerate(policies):
            logger.info(
                "  [%d] %s v%s — %s effective=%s",
                i + 1,
                p.policy_id,
                p.version,
                p.title[:60],
                p.effective_date,
            )

