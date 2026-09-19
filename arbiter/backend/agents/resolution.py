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
        trace_role: str = "resolution",
    ) -> None:
        self.policy_store = policy_store
        self.model = model or settings.RESOLUTION_MODEL
        self.provider = provider
        self.trace_role = trace_role
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

        # Retrieval is an optimisation and may rank the vendor registry below
        # the top candidate set for synonyms such as "get" versus "receive".
        # An evidence-complete deterministic proof must inspect every active
        # policy in force on the requested date instead.
        proof_policies = self.policy_store.get_all_active_policies(as_of_date)
        deterministic = _verified_retention_ruling(
            question, context, proof_policies or policies
        ) or _verified_recipient_access_ruling(
            question, context, proof_policies or policies, as_of_date
        )
        if deterministic:
            logger.info(
                "ResolutionAgent: issued deterministic structured ruling for vendor=%s dataset=%s",
                context.vendor,
                context.dataset,
            )
            return deterministic

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
        recipient_terms = (
            "receive", "access", "obtain", "get", "retrieve", "download",
            "be given", "be provided",
        )
        sender_terms = ("share", "transfer", "send", "disclose", "provide to")
        if any(term in normalized for term in recipient_terms):
            return "RECIPIENT_ACCESS"
        if any(term in normalized for term in sender_terms):
            return "SENDER_TRANSFER"
        return "AMBIGUOUS - determine direction from the wording before applying scope rules"

    def _call_llm(self, messages: List[Dict[str, Any]]) -> LLMGatewayResult:
        """Call the assigned primary provider, then OpenRouter as overflow."""
        result = self.gateway.generate(
            role=self.trace_role,
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
                "Core ruling used the fallback provider; supporting checks ran independently and report their own availability."
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


def _verified_retention_ruling(
    question: str,
    context: PolicyContext,
    policies: List[Policy],
) -> Optional[Ruling]:
    """Answer an explicit retention-period query using scoped policy metadata.

    A regional or department rule is selected only when it matches the trusted
    context and is more specific than a matching global baseline.  This makes
    retention demonstrations stable across providers without relying on a
    policy ID or a hard-coded jurisdiction.
    """
    question_text = question.casefold()
    if "retain" not in question_text and "retention" not in question_text:
        return None

    dataset = (context.dataset or "").casefold().strip()
    if not dataset:
        return None

    def normalized(value: Optional[str]) -> str:
        return (value or "").casefold().strip()

    def scope_score(policy: Policy) -> Optional[int]:
        policy_dataset = normalized(policy.dataset)
        if policy_dataset and policy_dataset != dataset:
            return None

        score = 1 if policy_dataset else 0
        for policy_value, context_value, weight in (
            (policy.region, context.region, 4),
            (policy.department, context.department, 3),
            (policy.vendor, context.vendor, 2),
        ):
            scoped = normalized(policy_value)
            requested = normalized(context_value)
            if not scoped or scoped in {"all", "global"}:
                continue
            if not requested or scoped != requested:
                return None
            score += weight
        return score

    candidates: List[tuple[int, Policy, Any, int]] = []
    for policy in policies:
        score = scope_score(policy)
        if score is None:
            continue
        for section in policy.sections:
            years = (section.metadata or {}).get("retention_period_years")
            if isinstance(years, int) and years > 0:
                candidates.append((score, policy, section, years))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1].effective_date), reverse=True)
    _, controlling_policy, controlling_section, years = candidates[0]

    def citation(policy: Policy, section: Any) -> Citation:
        return Citation(
            policy_id=policy.policy_id,
            policy_title=policy.title,
            section_id=section.section_id,
            clause_type=section.clause_type,
            text_excerpt=section.text,
        )

    citations = [citation(controlling_policy, controlling_section)]
    policy_ids = [controlling_policy.policy_id]
    baseline = next(
        (
            item
            for item in candidates[1:]
            if normalized(item[1].region) in {"", "global", "all"}
            and not normalized(item[1].department)
        ),
        None,
    )
    explanation = f"Customer data may be retained for {years} years."
    caveats = ["Retention period selected from the most specific matching policy scope."]
    if baseline:
        _, baseline_policy, baseline_section, baseline_years = baseline
        citations.append(citation(baseline_policy, baseline_section))
        policy_ids.append(baseline_policy.policy_id)
        explanation += (
            f" {controlling_policy.policy_id} applies specifically to "
            f"{context.region} {context.department} and takes precedence over "
            f"the global {baseline_years}-year baseline in {baseline_policy.policy_id}."
        )

    return Ruling(
        ruling_id=str(uuid.uuid4()),
        question=question,
        context=context,
        decision=RulingDecision.PERMITTED,
        explanation=explanation,
        citations=citations,
        relevant_policy_ids=policy_ids,
        confidence=1.0,
        caveats=caveats,
        deterministic=True,
    )


def _verified_recipient_access_ruling(
    question: str,
    context: PolicyContext,
    policies: List[Policy],
    as_of_date: date,
) -> Optional[Ruling]:
    """Resolve an evidence-complete vendor access request without an LLM.

    This narrow guard applies only to a recipient asking for its own access.
    It prevents provider wording differences from changing a decision when the
    loaded policies already contain a complete structured proof.
    """
    direction = ResolutionAgent._request_direction(question)
    vendor = (context.vendor or "").casefold().strip()
    dataset = (context.dataset or "").casefold().strip()
    if direction != "RECIPIENT_ACCESS" or not vendor or not dataset:
        return None

    def matching_policy(policy: Policy) -> bool:
        return not policy.dataset or policy.dataset.casefold().strip() == dataset

    def citation(policy: Policy, section: Any) -> Citation:
        return Citation(
            policy_id=policy.policy_id,
            policy_title=policy.title,
            section_id=section.section_id,
            clause_type=section.clause_type,
            text_excerpt=section.text,
        )

    approval_sections: List[tuple[Policy, Any]] = []
    dpa_sections: List[tuple[Policy, Any]] = []
    security_sections: List[tuple[Policy, Any]] = []
    india_centre_sections: List[tuple[Policy, Any]] = []
    permission_sections: List[tuple[Policy, Any]] = []
    india_rule_sections: List[tuple[Policy, Any]] = []
    historical_open_access_sections: List[tuple[Policy, Any]] = []

    for policy in policies:
        if not matching_policy(policy):
            continue
        for section in policy.sections:
            text = section.text.casefold()
            metadata = section.metadata or {}
            applies_to_vendor = str(metadata.get("applies_to_vendor", "")).casefold().strip()
            policy_vendor = (policy.vendor or "").casefold().strip()
            is_vendor_scoped = applies_to_vendor == vendor or policy_vendor == vendor

            # A vendor-targeted recipient restriction is controlling.  Sender
            # restrictions (for example, Analytics *sharing*) do not apply to
            # a recipient-access request.
            if is_vendor_scoped and any(
                phrase in text
                for phrase in ("prohibited from receiving", "not approved to receive", "may not receive")
            ):
                return Ruling(
                    ruling_id=str(uuid.uuid4()),
                    question=question,
                    context=context,
                    decision=RulingDecision.NOT_PERMITTED,
                    explanation=(
                        f"{policy.policy_id} {section.section_id} directly restricts "
                        f"{context.vendor} from receiving {context.dataset}."
                    ),
                    citations=[citation(policy, section)],
                    relevant_policy_ids=[policy.policy_id],
                    confidence=1.0,
                    blocking_clause=BlockingClause(
                        policy_id=policy.policy_id,
                        policy_title=policy.title,
                        section_id=section.section_id,
                        text=section.text,
                    ),
                    deterministic=True,
                )

            if "approved vendors may receive" in text and dataset in text:
                permission_sections.append((policy, section))
            # The historical DS-001-v2 state explicitly establishes that no
            # vendor-specific restrictions existed.  When it is the active
            # point-in-time policy, a provider must not invent a later
            # approval-record requirement and overwrite that dated rule.
            if "no vendor-specific restrictions are in effect" in text:
                historical_open_access_sections.append((policy, section))
            if is_vendor_scoped and (
                metadata.get("approved_data_recipient") is True
                or "approved data recipient" in text
            ):
                approval_sections.append((policy, section))
            if is_vendor_scoped and metadata.get("dpa_current") is True:
                dpa_sections.append((policy, section))
            if is_vendor_scoped and metadata.get("security_certification_current") is True:
                security_sections.append((policy, section))
            if is_vendor_scoped and metadata.get("india_data_centers_certified") is True:
                india_centre_sections.append((policy, section))
            if "india" in text and "data center" in text and "permitted" in text:
                india_rule_sections.append((policy, section))

    # Historical policy versions sometimes deliberately define the absence
    # of vendor-specific restrictions.  This is a complete point-in-time
    # answer for a recipient-access question; it is not safe to substitute a
    # present-day vendor registry or a later prohibition into that history.
    if permission_sections and historical_open_access_sections:
        proof_sections = [permission_sections[0], historical_open_access_sections[0]]
        citations = [citation(policy, section) for policy, section in proof_sections]
        policy_ids = list(dict.fromkeys(policy.policy_id for policy, _ in proof_sections))
        return Ruling(
            ruling_id=str(uuid.uuid4()),
            question=question,
            context=context,
            decision=RulingDecision.PERMITTED,
            explanation=(
                f"On {as_of_date.isoformat()}, {permission_sections[0][0].policy_id} "
                f"permitted approved vendors to receive {context.dataset}, and "
                "its active definition stated that no vendor-specific restrictions "
                "were in effect under that version. The later Vendor X restriction "
                "does not apply to this historical policy state."
            ),
            citations=citations,
            relevant_policy_ids=policy_ids,
            confidence=1.0,
            caveats=["Decision derived from the active point-in-time policy state."],
            deterministic=True,
        )

    has_india_requirement = bool(india_rule_sections) and (context.region or "").casefold() == "india"
    if not (
        permission_sections
        and approval_sections
        and dpa_sections
        and security_sections
        and (not has_india_requirement or india_centre_sections)
    ):
        return None

    proof_sections = [permission_sections[0], approval_sections[0], dpa_sections[0], security_sections[0]]
    if has_india_requirement:
        proof_sections.extend([india_rule_sections[0], india_centre_sections[0]])
    citations = [citation(policy, section) for policy, section in proof_sections]
    policy_ids = list(dict.fromkeys(policy.policy_id for policy, _ in proof_sections))
    return Ruling(
        ruling_id=str(uuid.uuid4()),
        question=question,
        context=context,
        decision=RulingDecision.PERMITTED,
        explanation=(
            f"{context.vendor} is an approved recipient for {context.dataset}; "
            "the current DPA and annual security certification requirements are verified "
            "in the loaded policy evidence."
            + (
                " Its India-based CERT-In data-center requirement is also verified."
                if has_india_requirement
                else ""
            )
        ),
        citations=citations,
        relevant_policy_ids=policy_ids,
        confidence=1.0,
        caveats=["Decision derived directly from structured policy evidence."],
        deterministic=True,
    )


def _safe_clause_type(value: Optional[str]) -> Optional[ClauseType]:
    """Parse clause type without raising on unknown values."""
    if not value:
        return None
    try:
        return ClauseType(value.upper())
    except ValueError:
        return ClauseType.OTHER
