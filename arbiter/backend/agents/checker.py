"""
agents/checker.py - Adversarial Checker Agent
==============================================
The CheckerAgent performs an independent second-pass over a proposed Ruling,
actively trying to find policy-grounded flaws: missed exceptions, scope errors,
false premises, citation inaccuracies, and unsupported conclusions.

It runs on Groq (primary) and falls back to OpenRouter.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

from pydantic import BaseModel, Field, field_validator

from config import settings
from providers.gateway import LLMGateway
from providers.schemas import LLMGatewayResult
from schemas import (
    CheckerResult,
    CheckerStatus,
    Citation,
    Policy,
    Ruling,
)
from stores.policy_store import PolicyStore

logger = logging.getLogger(__name__)


def _strip_markdown_fences(text: str) -> str:
    """Clean LLM output: remove <think> blocks, markdown fences, extract JSON."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    m = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if m:
        text = m.group(1)
    return text.strip()


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Adversarial Checker for Arbiter. Your job is to ACTIVELY TRY TO FIND FLAWS in the proposed ruling.

Check for ALL of the following:
1. MISSED EXCEPTIONS: Are there exception clauses in the retrieved policies that the ruling failed to consider?
2. SUPERSESSION ERRORS: Is the ruling based on a superseded policy version when a newer version is active?
3. WRONG SCOPE: Does the ruling apply policies outside their scope (wrong region, department, or vendor)?
4. REGIONAL OVERRIDES: Are there regional policies that override the global ruling?
5. DEPARTMENT-SPECIFIC RULES: Are there department-specific rules that modify the general ruling?
6. CONFLICTING CLAUSES: Are there conflicting applicable clauses the ruling ignored?
7. FALSE PREMISES: Did the ruling accept any user assertions as policy evidence? \
(e.g., 'the exception is old' -- that is not policy evidence unless a policy says so)
8. UNSUPPORTED CONCLUSIONS: Does every conclusion have a direct policy citation? Flag any that don't.
9. CITATION ACCURACY: Do the cited clause texts actually say what the ruling claims they say?

CRITICAL: You must be genuinely adversarial. Look hard for flaws. But your objections must be \
policy-grounded -- you cannot object based on what you think the policy should say, only what it \
actually says.

Return ONLY valid JSON:
{
  "approved": true/false,
  "objections": ["list of specific, policy-grounded objections"],
  "missed_exceptions": ["exception clauses the ruling missed"],
  "wrong_scope_flags": ["scope issues"],
  "false_premise_flags": ["user assertions treated as facts"],
  "explanation": "overall assessment"
}

If no valid objections found, set approved=true and leave objection lists empty.
"""


class _CheckerLLMOutput(BaseModel):
    approved: bool
    objections: List[str] = Field(default_factory=list)
    missed_exceptions: List[str] = Field(default_factory=list)
    wrong_scope_flags: List[str] = Field(default_factory=list)
    false_premise_flags: List[str] = Field(default_factory=list)
    explanation: str = ""

    @field_validator(
        "objections", "missed_exceptions", "wrong_scope_flags", "false_premise_flags", mode="before"
    )
    @classmethod
    def normalize_string_lists(cls, value: object) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item) for item in value if item is not None]


# ---------------------------------------------------------------------------
# Helper: format citations for the user prompt
# ---------------------------------------------------------------------------

def _format_citations(citations: List[Citation]) -> str:
    """Render a list of Citation objects as a numbered, readable block."""
    if not citations:
        return "  (no citations provided)"
    lines: List[str] = []
    for i, c in enumerate(citations, start=1):
        txt = getattr(c, "text_excerpt", getattr(c, "text", ""))
        lines.append(
            f"  [{i}] Policy: {c.policy_id} | Section: {c.section_id}\n"
            f"      Text: {txt}"
        )
    return "\n".join(lines)


def _format_policies(policies: List[Policy]) -> str:
    """Render full policy text for the checker's context window."""
    if not policies:
        return "(no policies retrieved)"
    lines: List[str] = []
    for p in policies:
        sections_text = "\n".join(
            f"  [{s.section_id}] ({s.clause_type.value if hasattr(s.clause_type, 'value') else s.clause_type}) {s.text}"
            for s in p.sections
        )
        lines.append(
            f"--- Policy ID: {p.policy_id} | Version: {p.version} "
            f"| Effective: {p.effective_date} | Active: {p.is_active} ---\n"
            f"Title: {p.title}\n"
            f"Region: {p.region or 'GLOBAL'} | Dept: {p.department or 'ALL'} | Vendor: {p.vendor or 'ALL'} | Dataset: {p.dataset or 'ALL'}\n"
            f"Sections:\n{sections_text}\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CheckerAgent
# ---------------------------------------------------------------------------

class CheckerAgent:
    """
    Adversarially reviews a proposed Ruling against the full set of retrieved
    policies. Uses Groq (primary) -> OpenRouter (fallback).
    """

    def __init__(self, policy_store: PolicyStore) -> None:
        self.policy_store = policy_store
        self.gateway = LLMGateway()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(
        self,
        ruling: Ruling,
        policies: List[Policy],
        original_question: str,
        round_number: int = 1,
    ) -> CheckerResult:
        """
        Adversarially check the ruling.

        Parameters
        ----------
        ruling:
            The Ruling produced by the ResolutionAgent.
        policies:
            The full set of Policy objects retrieved for this question.
        original_question:
            The raw user question submitted to Arbiter.
        round_number:
            Which checker iteration this is (1-based). Exposed for logging.

        Returns
        -------
        CheckerResult
            approved=True  -> ruling passed adversarial review.
            approved=False -> one or more policy-grounded objections found.
        """
        logger.info(
            "CheckerAgent.check() | round=%d | ruling_decision=%s",
            round_number,
            ruling.decision,
        )

        formatted_citations = _format_citations(ruling.citations)
        formatted_policies = _format_policies(policies)

        user_message = (
            f"Original Question: {original_question}\n\n"
            f"Proposed Ruling:\n"
            f"- Decision: {ruling.decision}\n"
            f"- Explanation: {ruling.explanation}\n"
            f"- Citations used:\n{formatted_citations}\n\n"
            f"All Retrieved Policies (full text):\n{formatted_policies}\n\n"
            f"Carefully check: did the ruling miss any applicable exceptions, overrides, or "
            f"restrictions?\nDid the ruling accept any user assertions as policy facts?\n"
            f"Are all citations accurate?"
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        llm_result = await self._call_llm(messages)
        if not llm_result.success or not llm_result.payload:
            return CheckerResult(
                approved=False,
                status=CheckerStatus.CHECK_UNAVAILABLE,
                explanation="Adversarial verification unavailable; the ruling was not independently checked.",
                round_number=round_number,
            )
        return self._build_result(llm_result.payload, round_number)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_llm(self, messages: list) -> LLMGatewayResult:
        return self.gateway.generate(
            role="checker",
            messages=messages,
            model=settings.CHECKER_MODEL,
            response_schema=_CheckerLLMOutput,
            # gpt-oss counts its internal reasoning against this cap.  A
            # small cap can end mid-JSON, which is an unavailable check rather
            # than an adversarial result.  This leaves room for reasoning and
            # an auditable structured answer.
            max_tokens=4096,
        )

    def _build_result(self, raw: dict, round_number: int) -> CheckerResult:
        """
        Construct a CheckerResult from the raw LLM JSON output.
        Handles missing or malformed keys gracefully.
        """
        approved: bool = bool(raw.get("approved", False))
        objections: List[str] = _ensure_list(raw.get("objections", []))
        missed_exceptions: List[str] = _ensure_list(raw.get("missed_exceptions", []))
        wrong_scope_flags: List[str] = _ensure_list(raw.get("wrong_scope_flags", []))
        false_premise_flags: List[str] = _ensure_list(raw.get("false_premise_flags", []))
        explanation: str = str(raw.get("explanation", ""))

        # Sanity guard: if objections exist but approved is True, flip it.
        if objections and approved:
            logger.debug(
                "CheckerAgent: LLM returned approved=True with non-empty objections; "
                "setting approved=False."
            )
            approved = False

        # A model that rejects without supplying an actionable reason has not
        # passed verification.  Preserve that uncertainty rather than turning
        # it into a silent success.
        if not approved and not objections:
            logger.debug(
                "CheckerAgent: LLM returned approved=False with no objections; "
                "retaining an unverified revise state."
            )

        logger.info(
            "CheckerAgent: round=%d | approved=%s | objections=%d",
            round_number,
            approved,
            len(objections),
        )

        return CheckerResult(
            approved=approved,
            objections=objections,
            missed_exceptions=missed_exceptions,
            wrong_scope_flags=wrong_scope_flags,
            false_premise_flags=false_premise_flags,
            explanation=explanation,
            round_number=round_number,
            status=CheckerStatus.PASS if approved else CheckerStatus.REVISE,
        )


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

def _ensure_list(value: object) -> List[str]:
    """Coerce a value to List[str], tolerating None or non-list types."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    return [str(value)]


def _strip_markdown_fences(text: str) -> str:
    """
    Remove ```json ... ``` or ``` ... ``` wrappers that some models emit
    even when asked for raw JSON.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
