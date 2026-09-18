"""
agents/remediation.py - Arbiter Remediation Agent
==================================================
Activates ONLY after a NOT_PERMITTED ruling.

Two branches:
  A. WAIVER  — a policy-defined waiver/exception process exists.
               Return the exact steps from the policy text.
  B. SIMULATION — no policy-defined waiver exists.
               Return a hypothetical change for the Simulation agent.

NEVER invents approval processes, managers, forms, or procedures.
NEVER invents exceptions not present in the policy corpus.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from config import settings
from providers.gateway import LLMGateway
from schemas import (
    BlockingClause,
    Citation,
    ClauseType,
    Policy,
    RemediationResult,
    RemediationStep,
    RemediationType,
    Ruling,
)
from stores.policy_store import PolicyStore

logger = logging.getLogger(__name__)


class _RemediationLLMOutput(BaseModel):
    remediation_type: str
    is_possible: bool
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    required_approval: Optional[str] = None
    supporting_policy_ids: List[str] = Field(default_factory=list)
    supporting_section_ids: List[str] = Field(default_factory=list)
    hypothetical_change: Optional[str] = None
    explanation: str

    @field_validator("steps", mode="before")
    @classmethod
    def normalize_steps(cls, value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, dict):
            value = [value]
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @field_validator("supporting_policy_ids", "supporting_section_ids", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item) for item in value if item is not None]

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

REMEDIATION_SYSTEM = """You are the Remediation Analyst for Arbiter.

A NOT_PERMITTED ruling has been made. Your task: inspect the policy corpus to \
determine whether a legitimate, POLICY-DEFINED path to permission exists.

CRITICAL RULES (never violate):
- ONLY return remediation steps that are EXPLICITLY stated in the policy documents.
- NEVER invent approval processes, managers, forms, committees, or legal procedures.
- NEVER invent exceptions that are not present in the retrieved policies.
- The phrase "This restriction may not be waived" means Branch B (no waiver possible).
- Do not confuse hypothetical possibilities with actual policy provisions.

BRANCH A — WAIVER:
Use this when the policy corpus contains an explicit waiver / exception process.
Return:
{
  "remediation_type": "WAIVER",
  "is_possible": true,
  "steps": [
    {"step_number": 1, "description": "<exact wording from policy>", "required_approval": "<who or null>"}
  ],
  "required_approval": "<final approver from policy or null>",
  "supporting_policy_ids": ["<ids of policies containing the waiver>"],
  "supporting_section_ids": ["<section ids>"],
  "hypothetical_change": null,
  "explanation": "<which policy defines this process>"
}

BRANCH B — SIMULATION:
Use this when no policy-defined waiver exists (or the restriction is explicitly non-waivable).
Return:
{
  "remediation_type": "SIMULATION",
  "is_possible": false,
  "steps": [],
  "required_approval": null,
  "supporting_policy_ids": [],
  "supporting_section_ids": [],
  "hypothetical_change": "<brief description of the policy change that WOULD allow permission>",
  "explanation": "<why no waiver path exists>"
}
"""


def _strip_fences(text: str) -> str:
    """Clean LLM output: remove <think> blocks, markdown fences, extract JSON."""
    text = text.strip()
    # Strip qwen <think>...</think> reasoning blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    # Extract first JSON object if there's surrounding text
    m = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if m:
        text = m.group(1)
    return text.strip()


def _fmt_policy(p: Policy) -> str:
    lines = [f"POLICY {p.policy_id} ({p.title} v{p.version}):"]
    for s in p.sections:
        lines.append(f"  [{s.section_id}] {s.clause_type}: {s.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RemediationAgent
# ---------------------------------------------------------------------------


class RemediationAgent:
    """Determines the remediation path (or absence thereof) for NOT_PERMITTED rulings."""

    def __init__(self, policy_store: PolicyStore) -> None:
        self.policy_store = policy_store
        self.gateway = LLMGateway()

    async def find_remediation(
        self,
        ruling: Ruling,
        policies: List[Policy],
    ) -> RemediationResult:
        """Inspect the blocking clause and available policies for a waiver path."""
        blocking = ruling.blocking_clause
        if not blocking:
            # No explicit blocking clause — use a SIMULATION default
            return RemediationResult(
                ruling_id=ruling.ruling_id,
                remediation_type=RemediationType.SIMULATION,
                is_possible=False,
                steps=[],
                explanation=(
                    "The NOT_PERMITTED ruling did not cite a specific blocking clause, "
                    "so no targeted waiver path can be identified."
                ),
                hypothetical_change=(
                    "Identify and remove the specific prohibition that applies to this context."
                ),
            )

        blocking_text = (
            f"Policy: {blocking.policy_id} | {blocking.policy_title}\n"
            f"Section: {blocking.section_id or 'N/A'}\n"
            f"Text: {blocking.text}"
        )
        policy_block = "\n\n".join(_fmt_policy(p) for p in policies)

        user_msg = (
            f"Blocking Clause:\n{blocking_text}\n\n"
            f"Available Policy Corpus (search for WAIVER and PROCEDURE clauses):\n"
            f"{policy_block}\n\n"
            "Is there a legitimate, policy-defined path to permission?"
        )

        raw = self._call_llm(
            [
                {"role": "system", "content": REMEDIATION_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        return self._parse_result(raw, ruling)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = self.gateway.generate(
            role="remediation",
            messages=messages,
            model=settings.RESOLUTION_MODEL,
            response_schema=_RemediationLLMOutput,
            # Leave room for gpt-oss reasoning before the structured result.
            max_tokens=3072,
        )
        if result.success and result.payload:
            return result.payload
        # An unavailable remediation analysis cannot be presented as a waiver.
        # Offer only the existing, explicitly labelled hypothetical route.
        return {
            "remediation_type": "SIMULATION",
            "is_possible": False,
            "steps": [],
            "explanation": "Remediation analysis unavailable; no policy-defined path was verified.",
            "hypothetical_change": None,
        }

    def _parse_result(self, raw: Dict[str, Any], ruling: Ruling) -> RemediationResult:
        rtype_str = raw.get("remediation_type", "SIMULATION").upper()
        try:
            rtype = RemediationType(rtype_str)
        except ValueError:
            rtype = RemediationType.SIMULATION

        steps: List[RemediationStep] = []
        for s in raw.get("steps") or []:
            if isinstance(s, dict):
                steps.append(
                    RemediationStep(
                        step_number=int(s.get("step_number", len(steps) + 1)),
                        description=s.get("description", ""),
                        required_approval=s.get("required_approval"),
                    )
                )

        return RemediationResult(
            ruling_id=ruling.ruling_id,
            remediation_type=rtype,
            is_possible=bool(raw.get("is_possible", False)),
            steps=steps,
            required_approval=raw.get("required_approval"),
            supporting_policy_ids=raw.get("supporting_policy_ids") or [],
            supporting_section_ids=raw.get("supporting_section_ids") or [],
            hypothetical_change=raw.get("hypothetical_change"),
            explanation=raw.get("explanation") or "No explanation provided.",
        )
