"""
agents/precedent.py - Precedent Agent
======================================
The PrecedentAgent looks up historically similar rulings in the precedent
store and uses an LLM to assess whether the current ruling is consistent
with established precedent, or whether a discrepancy exists and why.

Primary provider : Cerebras (fast inference, no JSON-mode parameter).
Fallback chain   : Groq -> OpenRouter.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from config import settings
from providers.gateway import LLMGateway
from providers.schemas import LLMGatewayResult
from schemas import (
    PolicyContext,
    PrecedentMatch,
    PrecedentResult,
    PrecedentStatus,
    Ruling,
    StoredPrecedent,
)
from stores.precedent_store import PrecedentStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Precedent Analyst for Arbiter. Compare the current ruling with historical precedents.

Assess:
1. Are the historical rulings about the same or similar context?
2. Does the current ruling align with historical precedent?
3. If different, is the difference explained by:
   - Different context (different vendor, region, etc.)?
   - Policy changes (new versions, supersession)?
   - A genuine inconsistency that needs explanation?

Return ONLY valid JSON:
{
  "is_consistent": true/false,
  "discrepancy_explanation": "explain if inconsistent, or null",
  "consistency_explanation": "explain how current aligns with precedent, or null",
  "relevant_precedents": ["ruling_id list that are actually relevant"]
}
"""


class _PrecedentLLMOutput(BaseModel):
    is_consistent: bool
    discrepancy_explanation: Optional[str] = None
    consistency_explanation: Optional[str] = None
    relevant_precedents: List[str] = Field(default_factory=list)

    @field_validator("relevant_precedents", mode="before")
    @classmethod
    def normalize_relevant_precedents(cls, value: object) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item) for item in value if item is not None]


# ---------------------------------------------------------------------------
# PrecedentAgent
# ---------------------------------------------------------------------------

class PrecedentAgent:
    """
    Retrieves historically similar rulings and assesses consistency with
    the current proposed Ruling.

    Uses Cerebras (primary) -> Groq -> OpenRouter (fallback chain).
    """

    def __init__(self, precedent_store: PrecedentStore) -> None:
        self.precedent_store = precedent_store
        self.gateway = LLMGateway()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def find_precedent(
        self,
        question: str,
        context: PolicyContext,
        current_ruling: Ruling,
    ) -> PrecedentResult:
        """
        Find similar historical rulings and assess consistency.

        Steps
        -----
        1. Query the precedent store for up to 5 similar rulings.
        2. If none found, return an empty consistent result.
        3. Call the LLM to compare the current ruling with the precedents.
        4. Build and return a fully populated PrecedentResult.

        Parameters
        ----------
        question:
            The original user question.
        context:
            PolicyContext carrying department, region, vendor, etc.
        current_ruling:
            The Ruling produced by the ResolutionAgent (possibly already
            checker-approved).

        Returns
        -------
        PrecedentResult
            has_precedent=False if no similar rulings found.
            Otherwise includes a list of PrecedentMatch objects and an
            is_consistent flag with explanation.
        """
        logger.info(
            "PrecedentAgent.find_precedent() | question_snippet=%r",
            question[:80],
        )

        # --- Step 1: Retrieve similar rulings ---
        similar: List[StoredPrecedent] = self.precedent_store.find_similar_rulings(
            question=question,
            context=context,
            n_results=5,
        )

        if not similar:
            logger.info("PrecedentAgent: no similar precedents found.")
            return PrecedentResult(
                has_precedent=False,
                matches=[],
                is_consistent=None,
                discrepancy_explanation=None,
                consistency_explanation=None,
                status=PrecedentStatus.NO_RELEVANT_PRECEDENT,
            )

        # --- Step 2: Format and call LLM ---
        formatted_precedents = _format_precedents(similar)

        user_message = (
            f"Current Question: {question}\n"
            f"Current Context: {context}\n"
            f"Current Ruling Decision: {current_ruling.decision}\n"
            f"Current Ruling Explanation: {current_ruling.explanation}\n\n"
            f"Historical Precedents:\n{formatted_precedents}\n\n"
            f"Are these consistent? Explain."
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        llm_result = await self._call_llm(messages)
        if not llm_result.success or not llm_result.payload:
            logger.warning(
                "PrecedentAgent unavailable request_id=%s error_type=%s",
                llm_result.request_id,
                llm_result.error_type,
            )
            return PrecedentResult(
                has_precedent=True,
                matches=_build_matches(similar, []),
                is_consistent=None,
                consistency_explanation=None,
                discrepancy_explanation=None,
                summary="Historical consistency could not be verified.",
                status=PrecedentStatus.CHECK_UNAVAILABLE,
            )
        raw = llm_result.payload

        # --- Step 3: Build PrecedentMatch objects ---
        relevant_ids: List[str] = _ensure_list_str(raw.get("relevant_precedents", []))

        matches: List[PrecedentMatch] = _build_matches(similar, relevant_ids)

        # The gateway validates this required field before returning success.
        # Never allow a missing value to silently become "consistent".
        is_consistent: bool = bool(raw["is_consistent"])
        discrepancy_explanation: Optional[str] = raw.get("discrepancy_explanation") or None
        consistency_explanation: Optional[str] = raw.get("consistency_explanation") or None

        logger.info(
            "PrecedentAgent: found=%d | relevant=%d | consistent=%s",
            len(similar),
            len(relevant_ids),
            is_consistent,
        )

        return PrecedentResult(
            has_precedent=True,
            matches=matches,
            is_consistent=is_consistent,
            discrepancy_explanation=discrepancy_explanation,
            consistency_explanation=consistency_explanation,
            status=(
                PrecedentStatus.CONSISTENT
                if is_consistent else PrecedentStatus.INCONSISTENT
            ),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_llm(self, messages: list) -> LLMGatewayResult:
        return self.gateway.generate(
            role="precedent",
            messages=messages,
            model=settings.PRECEDENT_MODEL,
            primary_provider=settings.PRECEDENT_PROVIDER,
            response_schema=_PrecedentLLMOutput,
            # Leave room for gpt-oss reasoning plus the JSON comparison.
            max_tokens=3072,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (also exposed for testing)
# ---------------------------------------------------------------------------

def _format_precedents(precedents: List[StoredPrecedent]) -> str:
    """
    Render a list of StoredPrecedent objects into a readable text block
    suitable for inclusion in an LLM prompt.
    """
    if not precedents:
        return "(no historical precedents)"

    lines: List[str] = []
    for i, p in enumerate(precedents, start=1):
        ts = getattr(p, "timestamp", getattr(p, "created_at", "N/A"))
        ctx = p.context
        dept = getattr(ctx, "department", ctx.get("department") if isinstance(ctx, dict) else "N/A")
        region = getattr(ctx, "region", ctx.get("region") if isinstance(ctx, dict) else "N/A")
        vendor = getattr(ctx, "vendor", ctx.get("vendor") if isinstance(ctx, dict) else "N/A")
        lines.append(
            f"[Precedent {i}]\n"
            f"  Ruling ID  : {p.ruling_id}\n"
            f"  Question   : {p.question}\n"
            f"  Decision   : {p.decision}\n"
            f"  Explanation: {p.explanation}\n"
            f"  Date       : {ts}\n"
            f"  Context    : department={dept}, region={region}, vendor={vendor}\n"
        )
    return "\n".join(lines)


def _build_matches(
    precedents: List[StoredPrecedent],
    relevant_ids: List[str],
) -> List[PrecedentMatch]:
    """
    Convert StoredPrecedent objects to PrecedentMatch objects.
    Marks each match as relevant based on the LLM-identified relevant_ids.
    """
    relevant_set = set(relevant_ids)
    matches: List[PrecedentMatch] = []
    for p in precedents:
        ts = getattr(p, "timestamp", getattr(p, "created_at", None))
        matches.append(
            PrecedentMatch(
                ruling_id=p.ruling_id,
                question=p.question,
                decision=p.decision,
                explanation=p.explanation,
                created_at=str(ts) if ts else None,
                similarity_score=float(getattr(p, "similarity_score", 0.0) or 0.0),
                is_relevant=p.ruling_id in relevant_set,
                context=p.context if isinstance(p.context, PolicyContext) else PolicyContext(**(p.context if isinstance(p.context, dict) else {})),
            )
        )
    return matches


def _ensure_list_str(value: object) -> List[str]:
    """Coerce an arbitrary value to List[str]."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    return [str(value)]


def _strip_markdown_fences(text: str) -> str:
    """
    Strip ```json ... ``` or ``` ... ``` fences that some models include
    even when instructed to return raw JSON.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
