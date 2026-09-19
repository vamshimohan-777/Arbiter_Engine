"""
agents/sensitivity.py - Arbiter Sensitivity Agent
==================================================
Determines how fragile the ruling is by perturbing context fields
one at a time and re-running Resolution.

Strategy:
  - Perturb vendor, region, department, dataset with plausible alternatives
  - Call Resolution for each perturbation (using real retrieved policies)
  - Detect decision flips
  - Return the nearest / smallest flip
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import date
from typing import List, Optional

from config import settings
from schemas import (
    AnalysisStatus,
    Policy,
    PolicyContext,
    Ruling,
    RulingDecision,
    SensitivityFlip,
    SensitivityResult,
)
from stores.policy_store import PolicyStore

logger = logging.getLogger(__name__)

# Plausible alternative values for each dimension (drawn from the demo corpus)
_VENDOR_ALTS = ["Vendor X", "Vendor Y", "Vendor Z"]
_REGION_ALTS = ["GLOBAL", "EU", "INDIA", "US", "APAC"]
_DEPT_ALTS   = ["ANALYTICS", "FINANCE", "ENGINEERING", "LEGAL"]
_DATASET_ALTS = ["Dataset Y", "Dataset Z", "Dataset W"]


class SensitivityAgent:
    """Probes the decision boundary of a ruling by perturbing context fields."""

    def __init__(self, policy_store: PolicyStore) -> None:
        self.policy_store = policy_store
        # Import here to avoid circular imports
        from agents.resolution import ResolutionAgent
        from agents.retrieval import RetrievalAgent
        self._resolution = ResolutionAgent(
            policy_store,
            # Re-use the proven core model. Sensitivity requires the same
            # structured policy ruling contract as resolution, so a smaller
            # model should be an explicit deployment choice, not the default.
            model=settings.RESOLUTION_MODEL,
            trace_role="sensitivity",
        )
        self._retrieval = RetrievalAgent(policy_store)

    async def analyze(
        self,
        original_ruling: Ruling,
        original_question: str,
        context: PolicyContext,
        as_of_date: date,
    ) -> SensitivityResult:
        """Perturb each context field and detect ruling flips."""
        flips: List[SensitivityFlip] = []
        total_tested = 0
        failed_perturbations = 0

        tasks = []

        # Build perturbation list — only perturb fields that were specified
        perturbations: List[tuple[str, Optional[str], str]] = []  # (field, orig, new)

        # Vendor, region, and department come from authenticated server-side
        # identity.  Varying them produces a different principal, not a
        # meaningful sensitivity signal for the current user.  Only probe the
        # request-controlled dataset dimension.
        if context.dataset:
            alternatives = [item for item in _DATASET_ALTS if item.casefold() != context.dataset.casefold()]
            if alternatives:
                perturbations.append(("dataset", context.dataset, alternatives[0]))

        perturbations = perturbations[:1]

        # Run perturbations sequentially to respect rate limits
        for field, orig_val, new_val in perturbations:
            total_tested += 1
            new_ctx = _perturb(context, field, new_val)
            try:
                policies = await self._retrieval.retrieve(
                    original_question, new_ctx, as_of_date, n_results=6
                )
                new_ruling = await self._resolution.resolve(
                    original_question, new_ctx, policies, as_of_date, is_draft=True
                )
                if new_ruling.decision != original_ruling.decision:
                    flips.append(
                        SensitivityFlip(
                            field=field,
                            original_value=orig_val,
                            new_value=new_val,
                            original_decision=original_ruling.decision,
                            new_decision=new_ruling.decision,
                            explanation=(
                                f"Changing {field} from '{orig_val}' to '{new_val}' "
                                f"changes the ruling from {original_ruling.decision} "
                                f"to {new_ruling.decision}. "
                                f"{new_ruling.explanation[:200]}"
                            ),
                        )
                    )
                    break  # Found the nearest flip boundary
            except Exception as exc:
                failed_perturbations += 1
                logger.warning("Sensitivity perturbation (%s=%s) failed: %s", field, new_val, exc)

        # The "nearest" flip is the one with the smallest field change (vendor changes are most targeted)
        field_priority = {"vendor": 0, "dataset": 1, "department": 2, "region": 3}
        nearest: Optional[SensitivityFlip] = None
        if flips:
            flips.sort(key=lambda f: field_priority.get(f.field, 99))
            nearest = flips[0]

        is_fragile = len(flips) > 0
        if perturbations and failed_perturbations == len(perturbations):
            status = AnalysisStatus.CHECK_UNAVAILABLE
            summary = "Sensitivity analysis unavailable; no context variations could be evaluated."
        elif nearest:
            status = AnalysisStatus.SUCCESS
            summary = (
                f"Fragile — changing {nearest.field} from "
                f"'{nearest.original_value}' to '{nearest.new_value}' "
                f"flips the ruling from {nearest.original_decision} to {nearest.new_decision}."
            )
        elif not perturbations:
            status = AnalysisStatus.NO_ELIGIBLE_CASES
            summary = "Sensitivity analysis is not applicable: no request-controlled dataset was supplied."
        else:
            status = AnalysisStatus.SUCCESS
            summary = "Ruling appears stable across tested request context variations."

        return SensitivityResult(
            ruling_id=original_ruling.ruling_id,
            flips=flips,
            nearest_flip=nearest,
            is_fragile=is_fragile,
            summary=summary,
            total_perturbations_tested=total_tested,
            status=status,
        )


def _perturb(context: PolicyContext, field: str, value: str) -> PolicyContext:
    """Return a copy of PolicyContext with one field changed."""
    data = context.model_dump()
    data[field] = value
    return PolicyContext(**data)
