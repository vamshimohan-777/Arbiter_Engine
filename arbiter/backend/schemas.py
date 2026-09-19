"""
schemas.py - Pydantic domain models for the Arbiter policy-reasoning system.

All agents and stores communicate exclusively through these contracts.
No business logic lives here - only data shapes and enumerations.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ClauseType(str, Enum):
    """Semantic classification of a policy section / clause."""

    PERMISSION = "PERMISSION"
    RESTRICTION = "RESTRICTION"
    OBLIGATION = "OBLIGATION"
    EXCEPTION = "EXCEPTION"
    OVERRIDE = "OVERRIDE"
    DEFINITION = "DEFINITION"
    SCOPE = "SCOPE"
    PENALTY = "PENALTY"
    PROCEDURE = "PROCEDURE"
    WAIVER = "WAIVER"
    RULE = "RULE"           # generic rule clause (used in policy JSON files)
    OTHER = "OTHER"


class RulingDecision(str, Enum):
    """Top-level verdict returned by the Arbiter orchestrator."""

    PERMITTED = "PERMITTED"
    NOT_PERMITTED = "NOT_PERMITTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class CheckerStatus(str, Enum):
    """Whether adversarial verification ran and what it concluded."""

    PASS = "PASS"
    REVISE = "REVISE"
    CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"


class PrecedentStatus(str, Enum):
    """Outcome of the precedent analysis, separate from the core ruling."""

    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    NO_RELEVANT_PRECEDENT = "NO_RELEVANT_PRECEDENT"
    CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"


class AnalysisStatus(str, Enum):
    """Status shared by optional analysis agents."""

    SUCCESS = "SUCCESS"
    NO_ELIGIBLE_CASES = "NO_ELIGIBLE_CASES"
    CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"
    FAILED = "FAILED"


class RelationshipType(str, Enum):
    """Edge semantics for the policy relationship graph."""

    SUPERSEDES = "SUPERSEDES"
    EXCEPTION_TO = "EXCEPTION_TO"
    OVERRIDE = "OVERRIDE"
    REFERENCES = "REFERENCES"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    EXTENDS = "EXTENDS"
    DERIVED_FROM = "DERIVED_FROM"


class ScanSeverity(str, Enum):
    """Severity level for a compliance scan finding."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


# ---------------------------------------------------------------------------
# Core policy models
# ---------------------------------------------------------------------------


class PolicySection(BaseModel):
    """A single clause or section within a policy document."""

    section_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: Optional[str] = None   # filled in by the loader; not required in JSON
    clause_type: ClauseType = ClauseType.OTHER
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class Policy(BaseModel):
    """Full policy document including metadata and parsed sections."""

    policy_id: str
    title: str
    version: str = "1.0"
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    region: Optional[str] = None
    department: Optional[str] = None
    vendor: Optional[str] = None
    dataset: Optional[str] = None
    category: Optional[str] = None
    supersedes: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    json_path: Optional[str] = None
    is_active: bool = True
    sections: List[PolicySection] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}

    @field_validator("effective_date", "expiry_date", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> Optional[date]:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        if isinstance(v, str) and v:
            return date.fromisoformat(v)
        raise ValueError(f"Cannot parse date: {v!r}")


class PolicyContext(BaseModel):
    """Contextual information attached to an inbound question / request."""

    region: Optional[str] = None
    department: Optional[str] = None
    vendor: Optional[str] = None
    dataset: Optional[str] = None
    user_role: Optional[str] = None
    additional_context: Dict[str, Any] = Field(default_factory=dict)


class IdentityContext(BaseModel):
    """Server-verified attributes used as trusted policy context."""

    user_id: str
    display_name: str
    vendor: str
    region: str
    department: str
    role: str
    permissions: List[str] = Field(default_factory=list)
    status: str = "active"
    # Returned only at sign-in so local cross-origin clients can restore a
    # signed session when browser cookie handling is unavailable.
    session_token: Optional[str] = None


class Citation(BaseModel):
    """A reference to a specific policy section used to support a ruling."""

    policy_id: str
    policy_title: str
    section_id: Optional[str] = None
    clause_type: Optional[ClauseType] = None
    text_excerpt: str
    relevance_score: float = Field(ge=0.0, le=1.0, default=1.0)

    model_config = {"use_enum_values": True}


class BlockingClause(BaseModel):
    """Identifies the specific clause that caused a NOT_PERMITTED ruling."""

    policy_id: str
    policy_title: str
    section_id: Optional[str] = None
    text: str


class Ruling(BaseModel):
    """The final verdict produced by the Arbiter orchestrator."""

    ruling_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str
    context: PolicyContext
    decision: RulingDecision
    explanation: str
    citations: List[Citation] = Field(default_factory=list)
    relevant_policy_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    caveats: List[str] = Field(default_factory=list)
    blocking_clause: Optional[BlockingClause] = None
    # Operational provenance, not policy evidence.  It allows the
    # orchestrator to avoid blocking a valid fallback ruling on optional
    # follow-up agents when the primary provider is unavailable.
    provider_fallback_used: bool = False
    # True only when the decision was derived directly from structured policy
    # evidence rather than from a generative provider response.
    deterministic: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"use_enum_values": True}


class StoredPrecedent(BaseModel):
    """A past ruling retrieved from the precedent store."""

    ruling_id: str
    question: str
    context: PolicyContext
    decision: RulingDecision
    explanation: str
    citations: List[Citation] = Field(default_factory=list)
    relevant_policy_ids: List[str] = Field(default_factory=list)
    timestamp: datetime

    model_config = {"use_enum_values": True}


class GraphNode(BaseModel):
    """A node in the policy relationship graph."""

    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    node_type: str = "policy"
    label: str
    policy_id: Optional[str] = None
    version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed edge in the policy relationship graph."""

    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    explanation: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_citation: Optional[str] = None

    model_config = {"use_enum_values": True}


class ScanFinding(BaseModel):
    """A single compliance finding produced by the Scanner agent."""

    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_id_a: str
    policy_title_a: str
    policy_id_b: str
    policy_title_b: str
    section_id: Optional[str] = None
    severity: ScanSeverity = ScanSeverity.MEDIUM
    finding_type: str
    relationship_type: Optional[RelationshipType] = None
    description: str
    recommendation: Optional[str] = None
    is_landmine: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Sensitivity agent schemas
# ---------------------------------------------------------------------------


class SensitivityFlip(BaseModel):
    """Records one perturbation that caused the ruling decision to flip."""

    field: str
    original_value: Optional[str] = None
    new_value: str
    original_decision: RulingDecision
    new_decision: RulingDecision
    explanation: str

    model_config = {"use_enum_values": True}


class SensitivityResult(BaseModel):
    """Aggregate output of the Sensitivity agent."""

    ruling_id: str
    flips: List[SensitivityFlip] = Field(default_factory=list)
    nearest_flip: Optional[SensitivityFlip] = None
    is_fragile: bool = False
    summary: str = ""
    total_perturbations_tested: int = 0
    status: AnalysisStatus = AnalysisStatus.SUCCESS


# ---------------------------------------------------------------------------
# Remediation agent schemas
# ---------------------------------------------------------------------------


class RemediationType(str, Enum):
    """Whether a policy-defined waiver path exists."""

    WAIVER = "WAIVER"
    SIMULATION = "SIMULATION"


class RemediationStep(BaseModel):
    """A single step in a policy-defined waiver process."""

    step_number: int
    description: str
    required_approval: Optional[str] = None


class RemediationResult(BaseModel):
    """Output of the Remediation agent for a NOT_PERMITTED ruling."""

    ruling_id: str
    remediation_type: RemediationType
    is_possible: bool
    steps: List[RemediationStep] = Field(default_factory=list)
    required_approval: Optional[str] = None
    supporting_policy_ids: List[str] = Field(default_factory=list)
    supporting_section_ids: List[str] = Field(default_factory=list)
    hypothetical_change: Optional[str] = None
    explanation: str

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Scanner agent schemas
# ---------------------------------------------------------------------------


class ScanResult(BaseModel):
    """Aggregate output of a corpus scan."""

    scan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    findings: List[ScanFinding] = Field(default_factory=list)
    landmines: List[ScanFinding] = Field(default_factory=list)
    graph_edges: List[GraphEdge] = Field(default_factory=list)
    total_policies_scanned: int = 0
    total_pairs_evaluated: int = 0
    summary: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Simulation agent schemas
# ---------------------------------------------------------------------------


class SimulationChangeType(str, Enum):
    """The kind of hypothetical mutation being applied to the policy corpus."""

    REMOVE_EXCEPTION = "REMOVE_EXCEPTION"
    ADD_EXCEPTION = "ADD_EXCEPTION"
    MODIFY_RULE = "MODIFY_RULE"
    REMOVE_POLICY = "REMOVE_POLICY"
    ADD_POLICY = "ADD_POLICY"


class SimulationChange(BaseModel):
    """Describes a single hypothetical mutation to the policy corpus."""

    change_type: SimulationChangeType
    target_policy_id: Optional[str] = None
    target_section_id: Optional[str] = None
    new_text: Optional[str] = None
    description: str

    model_config = {"use_enum_values": True}

    @field_validator("description", mode="before")
    @classmethod
    def keep_action_description(cls, value: Any) -> str:
        """Never let an empty client/model field erase the simulated action."""
        description = str(value or "").strip()
        return description or "Unspecified hypothetical policy change"


class SimulationImpact(BaseModel):
    """Before/after comparison for a single question under a hypothetical change."""

    question: str
    context: PolicyContext
    original_decision: RulingDecision
    hypothetical_decision: RulingDecision
    decision_changed: bool
    original_explanation: str
    hypothetical_explanation: str
    affected_policy_ids: List[str] = Field(default_factory=list)

    model_config = {"use_enum_values": True}


class SimulationResult(BaseModel):
    """Aggregate output of the Simulation agent."""

    simulation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    change: SimulationChange
    total_questions_tested: int = 0
    total_affected: int = 0
    flipped_impacts: List[SimulationImpact] = Field(default_factory=list)
    unaffected_impacts: List[SimulationImpact] = Field(default_factory=list)
    impact_summary: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: AnalysisStatus = AnalysisStatus.SUCCESS

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Precedent agent schemas
# ---------------------------------------------------------------------------


class PrecedentMatch(BaseModel):
    """A single historical ruling matched to the current question."""

    ruling_id: str
    question: str
    context: "PolicyContext"
    decision: RulingDecision
    similarity_score: float = Field(ge=0.0, le=1.0, default=0.0)
    explanation: str = ""
    created_at: Optional[Any] = None
    is_relevant: bool = True

    model_config = {"use_enum_values": True}


class PrecedentResult(BaseModel):
    """Output of the Precedent Agent."""

    has_precedent: bool = False
    matches: List[PrecedentMatch] = Field(default_factory=list)
    is_consistent: Optional[bool] = None
    discrepancy_explanation: Optional[str] = None
    consistency_explanation: Optional[str] = None
    summary: str = ""
    status: PrecedentStatus = PrecedentStatus.NO_RELEVANT_PRECEDENT


# ---------------------------------------------------------------------------
# API schemas (used by FastAPI endpoints)
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """Inbound payload for POST /api/ask."""

    question: str
    context: PolicyContext = Field(default_factory=PolicyContext)
    as_of_date: Optional["date"] = None
    session_id: Optional[str] = None


class AgentExecution(BaseModel):
    """Non-sensitive provenance for one agent result shown in the UI."""

    agent: str
    outcome: str
    provider: str
    model: Optional[str] = None
    status: str = "COMPLETED"
    fallback_used: bool = False
    calls: int = 1


class FinalResponse(BaseModel):
    """Top-level response returned by the orchestrator and FastAPI /api/ask."""

    session_id: str
    question: str
    context: PolicyContext
    ruling: "Ruling"
    checker_result: Optional["CheckerResult"] = None
    clarification: Optional["ClarificationRequest"] = None
    precedent: Optional[PrecedentResult] = None
    sensitivity: Optional["SensitivityResult"] = None
    remediation: Optional["RemediationResult"] = None
    graph_nodes: List["GraphNode"] = Field(default_factory=list)
    graph_edges: List["GraphEdge"] = Field(default_factory=list)
    agent_executions: List[AgentExecution] = Field(default_factory=list)
    processing_time_ms: int = 0
    mode: str = "ASK"

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Checker schemas
# ---------------------------------------------------------------------------


class CheckerResult(BaseModel):
    """Output of the CheckerAgent — adversarial review of a ruling."""

    approved: bool = True
    objections: List[str] = Field(default_factory=list)
    missed_exceptions: List[str] = Field(default_factory=list)
    wrong_scope_flags: List[str] = Field(default_factory=list)
    false_premise_flags: List[str] = Field(default_factory=list)
    explanation: str = ""
    round_number: int = 1
    status: CheckerStatus = CheckerStatus.PASS

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Clarification schemas
# ---------------------------------------------------------------------------


class ClarificationRequest(BaseModel):
    """The Resolution Agent's request for more context from the user."""

    question: str = ""
    missing_fields: List[str] = Field(default_factory=list)
    reason: str = ""
    suggested_options: Dict[str, List[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Policy status (legacy compat — used by structured_retrieve)
# ---------------------------------------------------------------------------


class PolicyStatus(str, Enum):
    """Lifecycle status of a policy document."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DRAFT = "DRAFT"
    REVOKED = "REVOKED"
