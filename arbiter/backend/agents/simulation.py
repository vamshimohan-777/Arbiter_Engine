"""
agents/simulation.py - Arbiter Simulation Agent
================================================
Implements What-If mode.

Given a hypothetical policy change (e.g. "Remove the Vendor X exception"),
this agent:
  1. Creates a temporary mutated copy of the policy corpus (never mutates real store)
  2. Retrieves relevant historical questions from PrecedentStore
  3. Re-runs Resolution with real policies (baseline) AND hypothetical policies
  4. Compares before/after decisions
  5. Returns a SimulationResult with full impact report

The real PolicyStore is NEVER modified.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import date
from typing import List, Optional

from schemas import (
    AnalysisStatus,
    Policy,
    PolicyContext,
    PolicySection,
    Ruling,
    RulingDecision,
    SimulationChange,
    SimulationChangeType,
    SimulationImpact,
    SimulationResult,
    StoredPrecedent,
)
from config import settings
from stores.policy_store import PolicyStore
from stores.precedent_store import PrecedentStore

logger = logging.getLogger(__name__)


class SimulationAgent:
    """Runs what-if policy change simulations.  Never mutates the real policy corpus."""

    def __init__(
        self,
        policy_store: PolicyStore,
        precedent_store: PrecedentStore,
    ) -> None:
        self.policy_store = policy_store
        self.precedent_store = precedent_store
        # Lazy imports to avoid circular dependency
        from agents.resolution import ResolutionAgent
        from agents.retrieval import RetrievalAgent
        self._resolution = ResolutionAgent(
            policy_store,
            model=settings.SIMULATION_MODEL,
            provider=settings.SIMULATION_PROVIDER,
            trace_role="simulation",
        )
        self._retrieval = RetrievalAgent(policy_store)

    async def simulate(
        self,
        change: SimulationChange,
        test_questions: Optional[List[str]] = None,
    ) -> SimulationResult:
        """Apply a hypothetical change and measure impact on historical rulings."""
        # The action is user-supplied simulation input, not model output.
        # Preserve a meaningful description even when an LLM fallback cannot
        # complete optional impact analysis.
        action_description = _describe_change(change)
        if change.description != action_description:
            change = change.model_copy(update={"description": action_description})

        # 1. Load real corpus
        real_policies = self.policy_store.get_all_active_policies(as_of_date=None)
        if not real_policies:
            return SimulationResult(
                simulation_id=str(uuid.uuid4()),
                change=change,
                total_questions_tested=0,
                total_affected=0,
                impact_summary=(
                    f"Hypothetical change: '{change.description}'. "
                    "No policies in corpus to simulate against."
                ),
                status=AnalysisStatus.NO_ELIGIBLE_CASES,
            )

        # 2. Apply hypothetical change to a deep copy (NEVER touch real_policies)
        hypothetical_policies = _apply_change(real_policies, change)

        # 3. Determine test questions
        if test_questions:
            questions_with_context: List[tuple[str, PolicyContext]] = [
                (q, PolicyContext()) for q in test_questions
            ]
        else:
            # Use precedent store to get historical rulings
            precedents = self.precedent_store.get_all_rulings()
            # Filter to those plausibly affected by the changed policy
            questions_with_context = [
                (p.question, p.context)
                for p in precedents
                if _ruling_may_be_affected(p, change)
            ]
            # If no precedents match, use all
            if not questions_with_context:
                questions_with_context = [(p.question, p.context) for p in precedents]
            # Cap at 10 to avoid excessive LLM calls
            questions_with_context = questions_with_context[:10]

        if not questions_with_context:
            return SimulationResult(
                simulation_id=str(uuid.uuid4()),
                change=change,
                total_questions_tested=0,
                total_affected=0,
                impact_summary=(
                    f"Hypothetical change: '{change.description}'. "
                    "No historical questions found to test against. "
                    "Seed precedents or provide test_questions."
                ),
                status=AnalysisStatus.NO_ELIGIBLE_CASES,
            )

        # 4. Compare before/after — sequential to avoid Groq rate limits
        #    Cap at 3 questions to keep response time under 60s
        as_of = date.today()
        questions_with_context = questions_with_context[:3]
        flipped: List[SimulationImpact] = []
        unaffected: List[SimulationImpact] = []
        failed_questions = 0
        fallback_limited = False

        for question, ctx in questions_with_context:
            try:
                real_retrieved = await self._retrieval.retrieve(question, ctx, as_of)
                real_ruling = await self._resolution.resolve(
                    question, ctx, real_retrieved, as_of, is_draft=True
                )
                # The mutation only needs the evidence used for the baseline
                # case. Passing the entire corpus makes fallback calls slow
                # and can cause the browser simulation timeout.
                hypothetical_retrieved = _matching_hypothetical_policies(
                    hypothetical_policies, real_retrieved, change
                )
                hypo_ruling = await self._resolution.resolve(
                    question, ctx, hypothetical_retrieved, as_of, is_draft=True
                )
                changed = real_ruling.decision != hypo_ruling.decision
                impact = SimulationImpact(
                    question=question,
                    context=ctx,
                    original_decision=real_ruling.decision,
                    hypothetical_decision=hypo_ruling.decision,
                    decision_changed=changed,
                    original_explanation=real_ruling.explanation[:300],
                    hypothetical_explanation=hypo_ruling.explanation[:300],
                    affected_policy_ids=hypo_ruling.relevant_policy_ids,
                )
                if changed:
                    flipped.append(impact)
                else:
                    unaffected.append(impact)
                # A valid OpenRouter fallback ruling is enough to produce an
                # impact result.  Stop after one case rather than risking a
                # timeout on multiple slow fallback requests.
                if real_ruling.provider_fallback_used or hypo_ruling.provider_fallback_used:
                    fallback_limited = True
                    logger.info("Simulation limited to one case after fallback-provider use.")
                    break
            except Exception as exc:
                failed_questions += 1
                logger.warning("Simulation question failed '%s': %s", question[:60], exc)

        total = len(flipped) + len(unaffected)
        if total == 0 and failed_questions:
            summary = (
                f"Hypothetical change: '{change.description}'. "
                "Simulation unavailable; eligible cases could not be evaluated."
            )
            status = AnalysisStatus.CHECK_UNAVAILABLE
        elif total == 0:
            summary = (
                f"Hypothetical change: '{change.description}'. "
                "No eligible precedent cases were found."
            )
            status = AnalysisStatus.NO_ELIGIBLE_CASES
        elif flipped:
            status = AnalysisStatus.SUCCESS
            flip_summary = "; ".join(
                f"'{i.question[:50]}' {i.original_decision}→{i.hypothetical_decision}"
                for i in flipped[:3]
            )
            summary = (
                f"Hypothetical change: '{change.description}'. "
                f"{len(flipped)}/{total} ruling(s) would flip. "
                f"Examples: {flip_summary}."
            )
        else:
            status = AnalysisStatus.SUCCESS
            summary = (
                f"Hypothetical change: '{change.description}'. "
                f"No rulings would change across {total} test questions."
            )

        if fallback_limited:
            summary += " Result based on one case because the fallback provider was used."

        return SimulationResult(
            simulation_id=str(uuid.uuid4()),
            change=change,
            total_questions_tested=total,
            total_affected=len(flipped),
            flipped_impacts=flipped,
            unaffected_impacts=unaffected,
            impact_summary=summary,
            status=status,
        )


# ---------------------------------------------------------------------------
# Hypothetical change application — operates on DEEP COPIES only
# ---------------------------------------------------------------------------


def _describe_change(change: SimulationChange) -> str:
    """Return a displayable action without relying on a provider response."""
    supplied = change.description.strip()
    if supplied and supplied != "Unspecified hypothetical policy change":
        return supplied

    target = change.target_policy_id or "the selected policy"
    section = f" section {change.target_section_id}" if change.target_section_id else ""
    templates = {
        SimulationChangeType.REMOVE_EXCEPTION: f"Remove an exception from {target}{section}",
        SimulationChangeType.ADD_EXCEPTION: f"Add an exception to {target}{section}",
        SimulationChangeType.MODIFY_RULE: f"Modify the rule in {target}{section}",
        SimulationChangeType.REMOVE_POLICY: f"Remove {target}",
        SimulationChangeType.ADD_POLICY: "Add a new policy",
    }
    return templates[change.change_type]


def _matching_hypothetical_policies(
    hypothetical_policies: List[Policy],
    baseline_policies: List[Policy],
    change: SimulationChange,
) -> List[Policy]:
    """Select the hypothetical counterparts of the baseline evidence set."""
    baseline_ids = {policy.policy_id for policy in baseline_policies}
    selected = [policy for policy in hypothetical_policies if policy.policy_id in baseline_ids]
    # An added policy has no baseline id and must be supplied explicitly.
    if change.change_type == SimulationChangeType.ADD_POLICY:
        selected.extend(
            policy for policy in hypothetical_policies
            if policy.policy_id.startswith("SIM-") and policy not in selected
        )
    return selected or hypothetical_policies[:1]


def _apply_change(policies: List[Policy], change: SimulationChange) -> List[Policy]:
    """Return a new list of Policy objects with the hypothetical change applied.

    The original list is never modified.
    """
    result: List[Policy] = []
    for pol in policies:
        # Deep copy first — never touch the original
        pol_copy = pol.model_copy(deep=True)

        if change.change_type == SimulationChangeType.REMOVE_POLICY:
            if pol.policy_id == change.target_policy_id:
                continue  # Exclude this policy entirely

        elif change.change_type == SimulationChangeType.REMOVE_EXCEPTION:
            if pol.policy_id == change.target_policy_id:
                new_sections = []
                for s in pol_copy.sections:
                    # Remove the targeted section or any EXCEPTION sections
                    is_target = (
                        change.target_section_id and s.section_id == change.target_section_id
                    )
                    if not is_target:
                        new_sections.append(s)
                pol_copy.sections = new_sections

        elif change.change_type == SimulationChangeType.ADD_EXCEPTION:
            if pol.policy_id == change.target_policy_id and change.new_text:
                new_section = PolicySection(
                    section_id=f"SIM-{uuid.uuid4().hex[:6]}",
                    policy_id=pol.policy_id,
                    clause_type="EXCEPTION",  # type: ignore[arg-type]
                    text=change.new_text,
                    metadata={"is_hypothetical": True},
                )
                pol_copy.sections.append(new_section)

        elif change.change_type == SimulationChangeType.MODIFY_RULE:
            if pol.policy_id == change.target_policy_id and change.new_text:
                for s in pol_copy.sections:
                    if change.target_section_id and s.section_id == change.target_section_id:
                        s.text = change.new_text
                        break

        # Mark as hypothetical in metadata
        pol_copy.metadata["is_hypothetical"] = True
        result.append(pol_copy)

    if change.change_type == SimulationChangeType.ADD_POLICY and change.new_text:
        new_pol = Policy(
            policy_id=f"SIM-{uuid.uuid4().hex[:8]}",
            title=f"Hypothetical: {change.description[:60]}",
            version="H1.0",
            effective_date=date.today(),
            category="HYPOTHETICAL",
            sections=[
                PolicySection(
                    section_id="SIM-S1",
                    policy_id="SIM-HYPOTHETICAL",
                    clause_type="RULE",  # type: ignore[arg-type]
                    text=change.new_text,
                    metadata={"is_hypothetical": True},
                )
            ],
            metadata={"is_hypothetical": True},
        )
        result.append(new_pol)

    return result


def _ruling_may_be_affected(precedent: StoredPrecedent, change: SimulationChange) -> bool:
    """Heuristic: does this precedent plausibly involve the changed policy?"""
    if not change.target_policy_id:
        return True
    return change.target_policy_id in precedent.relevant_policy_ids
