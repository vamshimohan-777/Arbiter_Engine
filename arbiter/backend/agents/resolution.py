"""
agents/resolution.py - Arbiter Resolution Agent
================================================
The ResolutionAgent is the core policy-reasoning engine.

Process:
  1. Clarification Gate - detect missing context before reasoning
  2. Supersession analysis - determine which policy versions are in effect
  3. Scope matching - which policies apply to this exact context
  4. Exception/override application - do exceptions modify the base rule?
  5. Conflict resolution - hierarchy when multiple policies conflict
  6. Draft ruling with full citations
  7. Revision pass when the Checker raises objections

Uses Groq (primary) → OpenRouter (fallback) via OpenAI-compatible API.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from config import settings
from providers.gateway import LLMGateway
from providers.schemas import LLMGatewayResult
from schemas import (
    BlockingClause,
    Citation,
    ClauseType,
    ClarificationRequest,
    Policy,
    PolicyContext,
    Ruling,
    RulingDecision,
)
from stores.policy_store import PolicyStore

logger = logging.getLogger(__name__)


class _ResolutionLLMOutput(BaseModel):
    decision: str
    explanation: str
    applicable_policy_ids: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    blocking_clause: Optional[Dict[str, Any]] = None
    relevant_relationships: List[str] = Field(default_factory=list)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: Any) -> str:
        normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
        if normalized not in {"PERMITTED", "NOT_PERMITTED", "NEEDS_CLARIFICATION"}:
            raise ValueError("decision must be a supported ruling value")
        return normalized

    @field_validator("explanation", mode="before")
    @classmethod
    def normalize_explanation(cls, value: Any) -> str:
        normalized = str(value).strip()
        if not normalized or normalized.lower() == "none":
            raise ValueError("explanation must be non-empty")
        return normalized

    @field_validator("applicable_policy_ids", "relevant_relationships", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item) for item in value if item is not None]

    @field_validator("citations", mode="before")
    @classmethod
    def normalize_citations(cls, value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, dict):
            value = [value]
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @field_validator("blocking_clause", mode="before")
    @classmethod
    def normalize_blocking_clause(cls, value: Any) -> Optional[Dict[str, Any]]:
        return value if isinstance(value, dict) else None

# ---------------------------------------------------------------------------
# Helpers (module-level, pure functions)
# ---------------------------------------------------------------------------

RESOLUTION_SYSTEM = """You are Arbiter, an agentic policy-reasoning system.

Your task: determine which policy ACTUALLY GOVERNS the given context.

Reasoning chain you MUST follow:
1. SUPERSESSION — identify the current active version of each policy family. \
Newer versions that supersede older ones override them.
2. SCOPE — which policies genuinely apply to this specific combination of \
vendor / region / department / dataset?
3. EXCEPTIONS — look for EXCEPTION or OVERRIDE clauses. Specific exceptions \
take precedence over general rules.
4. CONFLICT HIERARCHY — when multiple applicable policies conflict apply in order:
   a. Vendor-specific restrictions beat general policies.
   b. Regional policies beat global policies within their region.
   c. Department-specific policies beat general policies for that dept.
   d. Newer active versions beat older ones when scope is identical.
5. RULING — based strictly on policy evidence, decide:
   PERMITTED           → the action is explicitly or implicitly allowed
   NOT_PERMITTED       → a specific clause prohibits the action
   NEEDS_CLARIFICATION → context is insufficient to make a definitive ruling

CRITICAL RULES (never violate):
- NEVER invent policies, rules, exceptions, or approval processes.
- NEVER treat user assertions as policy evidence \
  (e.g. "the exception is old" is not a policy fact).
- VENDOR ISOLATION: NEVER apply restrictions for one specific vendor (e.g. 'Vendor X') to a different vendor (e.g. 'Vendor Y'). Vendor-specific policies (like VR-001) ONLY apply to the exact vendor named. If the question asks about Vendor Y, VR-001 (Vendor X) is IRRELEVANT and MUST NOT be cited as a blocking clause.
- Every conclusion MUST cite a specific policy_id and section_id.
- If evidence is insufficient, return NEEDS_CLARIFICATION.
- False premises embedded in the question must be ignored entirely.
- REQUEST DIRECTION: A question such as "Can I receive/access Dataset X?" from
  the authenticated vendor is a RECIPIENT-ACCESS request. Do NOT apply a
  department's external-sharing restriction merely because that vendor's user
  belongs to the department. Apply those restrictions only when the question
  asks that department to share, transfer, or send data to another party.
- CONCISENESS: Keep explanation under 150 words. Use only plain ASCII in all string values (use hyphen - not special Unicode dashes like - or –). Do NOT repeat the same point multiple times.

Return ONLY valid JSON — no markdown fences, no preamble, no trailing text:
{
  "decision": "PERMITTED | NOT_PERMITTED | NEEDS_CLARIFICATION",
  "explanation": "<concise step-by-step reasoning under 150 words citing specific policies>",
  "applicable_policy_ids": ["list of policy_ids that govern the answer"],
  "citations": [
    {
      "policy_id": "<exact policy_id>",
      "policy_title": "<exact title>",
      "section_id": "<exact section_id>",
      "clause_type": "<RULE|EXCEPTION|OVERRIDE|WAIVER|DEFINITION|PROCEDURE>",
      "text": "<verbatim clause text, max 80 chars>"
    }
  ],
  "blocking_clause": {
    "policy_id": "<policy_id>",
    "policy_title": "<title>",
    "section_id": "<section_id>",
    "text": "<verbatim blocking clause text, max 80 chars>"
  },
  "relevant_relationships": ["e.g. DS-001-v5 supersedes DS-001-v4"]
}
blocking_clause is REQUIRED when decision is NOT_PERMITTED (set to null otherwise).
"""

REVISION_SYSTEM = """You are Arbiter, revising a draft ruling in light of checker objections.

Apply the same reasoning rules as before.
If the objections are valid and policy-grounded → revise the ruling.
If the objections are NOT supported by actual policy text → maintain the \
ruling and explain why each objection fails.

Return the same JSON schema as a fresh ruling.
"""


def _strip_fences(text: str) -> str:
    """Clean LLM output: remove <think> blocks, markdown fences, extract JSON."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    m = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if m:
        text = m.group(1)
    return text.strip()


def _fmt_policy(p: Policy) -> str:
    """Format one Policy object into a human-readable block for prompts."""
    lines = [
        f"--- POLICY: {p.policy_id} | {p.title} | v{p.version} ---",
        f"Effective: {p.effective_date}  Expires: {p.expiry_date or 'N/A'}",
        f"Region: {p.region or 'GLOBAL'}  Dept: {p.department or 'ALL'}",
        f"Vendor: {p.vendor or 'ANY'}  Dataset: {p.dataset or 'ANY'}",
        f"Category: {p.category}",
    ]
    if p.supersedes:
        lines.append(f"Supersedes: {', '.join(p.supersedes)}")
    lines.append("Sections:")
    for s in p.sections:
        lines.append(f"  [{s.section_id}] ({s.clause_type}) {s.text}")
    return "\n".join(lines)


def _fmt_supersession(policies: List[Policy]) -> str:
    """Summarise supersession relationships among retrieved policies."""
    lines = []
    for p in policies:
        for sup in p.supersedes:
            lines.append(f"{p.policy_id} v{p.version} supersedes {sup}")
    return "\n".join(lines) if lines else "No explicit supersession relationships noted."


# ---------------------------------------------------------------------------
# ResolutionAgent
# ---------------------------------------------------------------------------


class ResolutionAgent:
    """Core policy reasoning engine.

    Responsibilities:
    - Run the clarification gate before reasoning begins.
    - Produce draft rulings with full citations.
    - Revise rulings on checker objections (bounded to MAX_CHECKER_ROUNDS).
    """

    def __init__(
        self,
        policy_store: PolicyStore,
        *,
        model: Optional[str] = None,
        provider: str = "groq",
    ) -> None:
        self.policy_store = policy_store
        self.model = model or settings.RESOLUTION_MODEL
        self.provider = provider
        self.gateway = LLMGateway()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def clarification_gate(
        self,
        question: str,
        policies: List[Policy],
        context: PolicyContext,
    ) -> Optional[ClarificationRequest]:
        """Check whether the supplied context is sufficient to reason.

        Critically: context can be supplied EITHER via the structured PolicyContext
        fields OR embedded directly in the question text.  We only ask for
        clarification when a dimension is genuinely ambiguous (multiple distinct
        values exist across retrieved policies) AND cannot be resolved from the
        question text.

        Returns a ClarificationRequest when clarification is truly needed,
        or None when context is sufficient to proceed.
        """
        if not policies:
            return None  # Let resolve() handle the empty case

        q_lower = question.lower()

        # ── Helper: is a value mentioned in the question? ──────────────────
        def _in_question(values: set) -> bool:
            return any(str(v).lower() in q_lower for v in values if v)

        # ── Collect distinct values from retrieved policies ─────────────────
        regions = {p.region for p in policies if p.region and p.region != "GLOBAL"}
        depts = {p.department for p in policies if p.department}
        vendors = {p.vendor for p in policies if p.vendor}
        datasets = {p.dataset for p in policies if p.dataset}

        missing: List[str] = []
        suggested: Dict[str, List[str]] = {}

        # Check if dimensions are mentioned in the question itself
        has_vendor_in_q = bool(re.search(r"\bvendor\s+[a-z0-9_-]+\b", q_lower))
        has_dept_in_q = bool(re.search(r"\b(analytics|engineering|finance|hr|legal|security|procurement)\b", q_lower))
        has_reg_in_q = bool(re.search(r"\b(india|us|usa|eu|europe|global|uk|australia|apac)\b", q_lower))
        has_dataset_in_q = bool(re.search(r"\b(dataset\s+[a-z0-9_-]+|operational logs|employee data|financial records)\b", q_lower))

        # Region: ambiguous if >1 region AND not in context AND not in question
        if len(regions) > 1 and not context.region and not _in_question(regions) and not has_reg_in_q:
            missing.append("region")
            suggested["region"] = sorted(regions)  # type: ignore[arg-type]

        # Department: ambiguous if >1 dept AND not in context AND not in question
        if len(depts) > 1 and not context.department and not _in_question(depts) and not has_dept_in_q:
            missing.append("department")
            suggested["department"] = sorted(depts)  # type: ignore[arg-type]

        # Vendor: ambiguous if >1 vendor AND not in context AND not in question
        if len(vendors) > 1 and not context.vendor and not _in_question(vendors) and not has_vendor_in_q:
            missing.append("vendor")
            suggested["vendor"] = sorted(vendors)  # type: ignore[arg-type]

        # Dataset: ambiguous if >1 dataset AND not in context AND not in question
        if len(datasets) > 1 and not context.dataset and not _in_question(datasets) and not has_dataset_in_q:
            missing.append("dataset")
            suggested["dataset"] = sorted(datasets)  # type: ignore[arg-type]

        if not missing:
            return None

        reason = (
            f"The applicable policies differ by {', '.join(missing)}. "
            "Please provide the missing context so I can give a precise ruling."
        )
        logger.info("Clarification needed: %s", missing)
        return ClarificationRequest(
            question=question,
            missing_fields=missing,
            reason=reason,
            suggested_options=suggested,
        )

    async def resolve(
        self,
        question: str,
        context: PolicyContext,
        policies: List[Policy],
        as_of_date: date,
        is_draft: bool = True,
    ) -> Ruling:
        """Produce a ruling (draft or final) from retrieved policy evidence."""
        if not policies:
            logger.warning("No policies retrieved for question: %s", question)
            return Ruling(
                ruling_id=str(uuid.uuid4()),
                question=question,
                context=context,
                decision=RulingDecision.NEEDS_CLARIFICATION,
                explanation=(
                    "No relevant policies were found in the corpus for this query. "
                    "Unable to make a ruling without policy evidence."
                ),
                citations=[],
                relevant_policy_ids=[],
                confidence=0.0,
                caveats=["No policy documents retrieved"],
            )

        user_msg = self._build_user_msg(question, context, policies, as_of_date)
        result = self._call_llm(
            [
                {"role": "system", "content": RESOLUTION_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        return self._parse_ruling(
            result.payload or {}, question, context, policies, as_of_date, is_draft,
            provider_fallback_used=result.fallback_used,
        )

    async def revise(
        self,
        original_ruling: Ruling,
        objections: List[str],
        policies: List[Policy],
        context: PolicyContext,
    ) -> Ruling:
        """Revise a draft ruling based on Checker objections."""
        as_of_date = original_ruling.timestamp.date()
        objection_block = "\n".join(f"- {o}" for o in objections)
        user_msg = (
            self._build_user_msg(
                original_ruling.question, context, policies, as_of_date
            )
            + f"""

--- ORIGINAL DRAFT RULING ---
Decision: {original_ruling.decision}
Explanation: {original_ruling.explanation}

--- CHECKER OBJECTIONS ---
{objection_block}

Reconsider the ruling.  If objections are policy-grounded → revise.
If objections are NOT backed by actual policy text → maintain and explain why.
"""
        )
        result = self._call_llm(
            [
                {"role": "system", "content": REVISION_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        return self._parse_ruling(
            result.payload or {}, original_ruling.question, context, policies, as_of_date,
            is_draft=False, provider_fallback_used=result.fallback_used,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_user_msg(
        self,
        question: str,
        context: PolicyContext,
        policies: List[Policy],
        as_of_date: date,
    ) -> str:
        policy_block = "\n\n".join(_fmt_policy(p) for p in policies)
        supersession_block = _fmt_supersession(policies)
        direction = self._request_direction(question)
        return f"""Question: {question}

Context:
  Vendor:     {context.vendor or 'not specified'}
  Region:     {context.region or 'not specified'}
  Department: {context.department or 'not specified'}
  Dataset:    {context.dataset or 'not specified'}
  As-of date: {as_of_date}

Request direction: {direction}
For RECIPIENT_ACCESS, the authenticated vendor is requesting access for itself;
the department is not the sender unless the question explicitly says it is
sharing or transferring data.

Policy Corpus:
{policy_block}

Supersession Relationships:
{supersession_block}
"""

    @staticmethod
    def _request_direction(question: str) -> str:
        """Distinguish vendor access requests from departmental transfers."""
        normalized = question.casefold()
        recipient_terms = ("receive", "access", "obtain", "be given", "be provided")
        sender_terms = ("share", "transfer", "send", "disclose", "provide to")
        if any(term in normalized for term in recipient_terms):
            return "RECIPIENT_ACCESS"
        if any(term in normalized for term in sender_terms):
            return "SENDER_TRANSFER"
        return "AMBIGUOUS - determine direction from the wording before applying scope rules"

    def _call_llm(self, messages: List[Dict[str, Any]]) -> LLMGatewayResult:
        """Call the assigned primary provider, then OpenRouter as overflow."""
        result = self.gateway.generate(
            role="resolution",
            messages=messages,
            model=self.model,
            primary_provider=self.provider,
            response_schema=_ResolutionLLMOutput,
            # This is also used for sensitivity and simulation reruns.  The
            # model reasons before emitting JSON, so a 2k cap can truncate a
            # valid ruling on complex policy bundles.
            max_tokens=4096,
        )
        if not result.success or not result.payload:
            raise RuntimeError("Reasoning service temporarily unavailable.")
        return result

    def _parse_ruling(
        self,
        raw: Dict[str, Any],
        question: str,
        context: PolicyContext,
        policies: List[Policy],
        as_of_date: date,
        is_draft: bool,
        provider_fallback_used: bool = False,
    ) -> Ruling:
        """Convert raw LLM JSON into a typed Ruling object."""
        policy_map: Dict[str, Policy] = {p.policy_id: p for p in policies}

        decision_str = raw.get("decision", "NEEDS_CLARIFICATION").upper()
        try:
            decision = RulingDecision(decision_str)
        except ValueError:
            decision = RulingDecision.NEEDS_CLARIFICATION

        # Build citations
        citations: List[Citation] = []
        for c in raw.get("citations") or []:
            pid = c.get("policy_id", "")
            pol = policy_map.get(pid)
            citations.append(
                Citation(
                    policy_id=pid,
                    policy_title=c.get("policy_title") or (pol.title if pol else pid),
                    section_id=c.get("section_id"),
                    clause_type=_safe_clause_type(c.get("clause_type")),
                    text_excerpt=c.get("text") or c.get("text_excerpt") or "",
                )
            )

        # Build blocking clause
        blocking: Optional[BlockingClause] = None
        bc = raw.get("blocking_clause")
        if decision == RulingDecision.NOT_PERMITTED and bc and isinstance(bc, dict):
            pid = bc.get("policy_id", "")
            pol = policy_map.get(pid)
            blocking = BlockingClause(
                policy_id=pid,
                policy_title=bc.get("policy_title") or (pol.title if pol else pid),
                section_id=bc.get("section_id"),
                text=bc.get("text") or "",
            )

        applicable_ids = raw.get("applicable_policy_ids") or list(policy_map.keys())
        relationships = raw.get("relevant_relationships") or []
        explanation = raw.get("explanation") or "No explanation provided."
        confidence = 0.85 if is_draft else 0.95

        caveats = list(relationships)
        if provider_fallback_used:
            caveats.append(
                "Core ruling used the fallback provider; optional verification and sensitivity checks were deferred."
            )

        return Ruling(
            ruling_id=str(uuid.uuid4()),
            question=question,
            context=context,
            decision=decision,
            explanation=explanation,
            citations=citations,
            relevant_policy_ids=applicable_ids,
            confidence=confidence,
            caveats=caveats,
            blocking_clause=blocking,
            provider_fallback_used=provider_fallback_used,
        )


def _safe_clause_type(value: Optional[str]) -> Optional[ClauseType]:
    """Parse clause type without raising on unknown values."""
    if not value:
        return None
    try:
        return ClauseType(value.upper())
    except ValueError:
        return ClauseType.OTHER
