"""
agents/scanner.py - Arbiter Corpus Scanner Agent
=================================================
Proactively detects policy landmines — conflicts, overrides, supersessions,
scope overlaps — without waiting for a user query.

Two-stage approach:
  Stage 1: Deterministic metadata overlap detection (fast, no LLM)
  Stage 2: LLM classification of candidate pairs (slow, targeted)

Results are stored in GraphStore as GraphEdge objects.
"""

from __future__ import annotations

import itertools
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel

from config import settings
from providers.gateway import LLMGateway
from schemas import (
    GraphEdge,
    Policy,
    RelationshipType,
    ScanFinding,
    ScanResult,
    ScanSeverity,
)
from stores.graph_store import GraphStore
from stores.policy_store import PolicyStore

logger = logging.getLogger(__name__)


class _ScannerLLMOutput(BaseModel):
    relationship_type: str
    severity: str
    explanation: str
    recommendation: Optional[str] = None
    is_landmine: bool = False

SCANNER_SYSTEM = """You are a policy conflict analyst for a compliance system.

Compare the two policies provided and classify their relationship.

Relationship types:
- SUPERSEDES        — one version explicitly replaces another (same policy family)
- OVERRIDE          — one policy explicitly overrides another for a specific context
- EXCEPTION_TO      — one policy creates an exception to a rule in another
- SCOPE_OVERLAP     — policies cover overlapping contexts but may give different answers
- CONFLICTS_WITH    — policies give directly contradictory mandatory guidance for the same context

For CONFLICTS_WITH and SCOPE_OVERLAP, assess severity:
  CRITICAL — directly contradictory mandatory rules, no reconciliation possible
  HIGH     — significant conflict that could produce wrong rulings without careful analysis
  MEDIUM   — overlap requiring careful interpretation
  LOW      — minor overlap, easily resolved by standard hierarchy rules

Return ONLY valid JSON (no markdown fences):
{
  "relationship_type": "SUPERSEDES | OVERRIDE | EXCEPTION_TO | SCOPE_OVERLAP | CONFLICTS_WITH",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "explanation": "<why these policies are related and the specific conflict/overlap>",
  "recommendation": "<what should be done to resolve this>",
  "is_landmine": true/false
}

is_landmine = true when severity is HIGH or CRITICAL.
"""


def _strip_fences(text: str) -> str:
    """Clean LLM output: remove <think> blocks, markdown fences, extract JSON."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if m:
        text = m.group(1)
    return text.strip()


def _fmt_pair(a: Policy, b: Policy) -> str:
    def fmt(p: Policy) -> str:
        lines = [
            f"Policy ID: {p.policy_id}",
            f"Title: {p.title}",
            f"Version: {p.version}",
            f"Effective: {p.effective_date}  Expires: {p.expiry_date or 'N/A'}",
            f"Region: {p.region or 'GLOBAL'}  Dept: {p.department or 'ALL'}",
            f"Vendor: {p.vendor or 'ANY'}  Dataset: {p.dataset or 'ANY'}",
            f"Category: {p.category}",
            f"Supersedes: {', '.join(p.supersedes) or 'none'}",
            "Sections:",
        ]
        for s in p.sections:
            lines.append(f"  [{s.section_id}] ({s.clause_type}): {s.text}")
        return "\n".join(lines)

    return f"=== POLICY A ===\n{fmt(a)}\n\n=== POLICY B ===\n{fmt(b)}"


def _dimensionally_related(a: Policy, b: Policy) -> bool:
    """Stage 1: quick structural check — are these policies worth comparing?"""
    # Same category
    if a.category and b.category and a.category == b.category:
        return True
    # Supersession relationship
    if a.policy_id in b.supersedes or b.policy_id in a.supersedes:
        return True
    # Shared vendor restriction
    if a.vendor and b.vendor and a.vendor == b.vendor:
        return True
    # Shared dataset scope
    if a.dataset and b.dataset and a.dataset == b.dataset:
        return True
    # Overlapping region / department AND same dataset
    region_overlap = (
        (not a.region or not b.region or a.region == b.region or
         "GLOBAL" in (a.region or "", b.region or ""))
    )
    dept_overlap = (
        (not a.department or not b.department or a.department == b.department)
    )
    if region_overlap and dept_overlap and a.dataset and a.dataset == b.dataset:
        return True
    return False


class CorpusScannerAgent:
    """Proactive corpus scanner — finds policy landmines before they cause bad rulings."""

    def __init__(self, policy_store: PolicyStore, graph_store: GraphStore) -> None:
        self.policy_store = policy_store
        self.graph_store = graph_store
        self.gateway = LLMGateway()

    async def scan(
        self,
        policies: Optional[List[Policy]] = None,
    ) -> ScanResult:
        """Run a full two-stage corpus scan."""
        if policies is None:
            policies = self.policy_store.get_all_active_policies(as_of_date=None)

        if not policies:
            logger.warning("No policies available for scanning.")
            return ScanResult(
                total_policies_scanned=0,
                summary="No policies found to scan.",
            )

        logger.info("Scanning %d policies ...", len(policies))

        # Stage 1: deterministic pair selection
        candidates: List[Tuple[Policy, Policy]] = []
        seen: Set[Tuple[str, str]] = set()
        for a, b in itertools.combinations(policies, 2):
            key = tuple(sorted([a.policy_id, b.policy_id]))
            if key not in seen and _dimensionally_related(a, b):
                seen.add(key)
                candidates.append((a, b))

        logger.info("Stage 1: %d candidate pairs selected for LLM analysis", len(candidates))

        # Stage 2: LLM classification — limit to 20 pairs to manage costs
        findings: List[ScanFinding] = []
        edges: List[GraphEdge] = []

        for a, b in candidates[:20]:
            result = self._classify_pair(a, b)
            if not result:
                continue

            rel_str = result.get("relationship_type", "SCOPE_OVERLAP").upper()
            sev_str = result.get("severity", "LOW").upper()

            try:
                rel = RelationshipType(rel_str)
            except ValueError:
                rel = RelationshipType.SCOPE_OVERLAP

            try:
                sev = ScanSeverity(sev_str)
            except ValueError:
                sev = ScanSeverity.LOW

            is_landmine = result.get("is_landmine", False) or sev in (ScanSeverity.HIGH, ScanSeverity.CRITICAL)

            finding = ScanFinding(
                finding_id=str(uuid.uuid4()),
                policy_id_a=a.policy_id,
                policy_title_a=a.title,
                policy_id_b=b.policy_id,
                policy_title_b=b.title,
                severity=sev,
                finding_type=rel_str,
                relationship_type=rel,
                description=result.get("explanation", ""),
                recommendation=result.get("recommendation"),
                is_landmine=is_landmine,
            )
            findings.append(finding)

            # Build graph edge
            edge = GraphEdge(
                edge_id=str(uuid.uuid4()),
                source_id=a.policy_id,
                target_id=b.policy_id,
                relationship_type=rel,
                explanation=result.get("explanation", ""),
                confidence=0.9 if sev in (ScanSeverity.HIGH, ScanSeverity.CRITICAL) else 0.7,
            )
            edges.append(edge)
            # Persist to graph store
            try:
                self.graph_store.upsert_edge(edge)
            except Exception as exc:
                logger.warning("Failed to store edge in graph store: %s", exc)

        landmines = [f for f in findings if f.is_landmine]
        total_findings = len(findings)
        summary = (
            f"Scanned {len(policies)} policies, evaluated {len(candidates)} pairs. "
            f"Found {total_findings} relationships, {len(landmines)} potential landmines."
        )

        logger.info(summary)
        return ScanResult(
            findings=findings,
            landmines=landmines,
            graph_edges=edges,
            total_policies_scanned=len(policies),
            total_pairs_evaluated=len(candidates),
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_pair(self, a: Policy, b: Policy) -> Optional[Dict[str, Any]]:
        """Call LLM to classify the relationship between two policies."""
        user_msg = _fmt_pair(a, b)
        messages = [
            {"role": "system", "content": SCANNER_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        result = self.gateway.generate(
            role="scanner",
            messages=messages,
            model=settings.SCANNER_MODEL,
            response_schema=_ScannerLLMOutput,
            # gpt-oss allocates part of its completion budget to reasoning;
            # leave room for a complete structured finding.
            max_tokens=3072,
        )
        if not result.success:
            logger.warning(
                "Scanner unavailable for pair (%s,%s): %s",
                a.policy_id, b.policy_id, result.error_type,
            )
            return None
        return result.payload
