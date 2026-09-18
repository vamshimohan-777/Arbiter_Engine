import pathlib

content = """\
\"\"\"
schemas.py - Pydantic domain models for the Arbiter policy-reasoning system.

All agents and stores communicate exclusively through these contracts.
No business logic lives here - only data shapes and enumerations.
\"\"\"

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
    \"\"\"Semantic classification of a policy section / clause.\"\"\"

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
    OTHER = "OTHER"


class RulingDecision(str, Enum):
    \"\"\"Top-level verdict returned by the Arbiter orchestrator.\"\"\"

    PERMITTED = "PERMITTED"
    NOT_PERMITTED = "NOT_PERMITTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class RelationshipType(str, Enum):
    \"\"\"Edge semantics for the policy relationship graph.\"\"\"

    SUPERSEDES = "SUPERSEDES"
    EXCEPTION_TO = "EXCEPTION_TO"
    OVERRIDE = "OVERRIDE"
    REFERENCES = "REFERENCES"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    EXTENDS = "EXTENDS"
    DERIVED_FROM = "DERIVED_FROM"


class ScanSeverity(str, Enum):
    \"\"\"Severity level for a compliance scan finding.\"\"\"

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


# ---------------------------------------------------------------------------
# Core policy models
# ---------------------------------------------------------------------------


class PolicySection(BaseModel):
    \"\"\"A single clause or section within a policy document.\"\"\"

    section_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str
    clause_type: ClauseType = ClauseType.OTHER
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class Policy(BaseModel):
    \"\"\"Full policy document including metadata and parsed sections.\"\"\"

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
    \"\"\"Contextual information attached to an inbound question / request.\"\"\"

    region: Optional[str] = None
    department: Optional[str] = None
    vendor: Optional[str] = None
    dataset: Optional[str] = None
    user_role: Optional[str] = None
    additional_context: Dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    \"\"\"A reference to a specific policy section used to support a ruling.\"\"\"

    policy_id: str
    policy_title: str
    section_id: Optional[str] = None
    clause_type: Optional[ClauseType] = None
    text_excerpt: str
    relevance_score: float = Field(ge=0.0, le=1.0, default=1.0)

    model_config = {"use_enum_values": True}


class BlockingClause(BaseModel):
    \"\"\"Identifies the specific clause that caused a NOT_PERMITTED ruling.\"\"\"

    policy_id: str
    policy_title: str
    section_id: Optional[str] = None
    text: str


class Ruling(BaseModel):
    \"\"\"The final verdict produced by the Arbiter orchestrator.\"\"\"

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
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"use_enum_values": True}


class StoredPrecedent(BaseModel):
    \"\"\"A past ruling retrieved from the precedent store.\"\"\"

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
    \"\"\"A node in the policy relationship graph.\"\"\"

    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    node_type: str = "policy"
    label: str
    policy_id: Optional[str] = None
    version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    \"\"\"A directed edge in the policy relationship graph.\"\"\"

    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    explanation: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_citation: Optional[str] = None

    model_config = {"use_enum_values": True}


class ScanFinding(BaseModel):
    \"\"\"A single compliance finding produced by the Scanner agent.\"\"\"

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
    \"\"\"Records one perturbation that caused the ruling decision to flip.\"\"\"

    field: str
    original_value: Optional[str] = None
    new_value: str
    original_decision: RulingDecision
    new_decision: RulingDecision
    explanation: str

    model_config = {"use_enum_values": True}


class SensitivityResult(BaseModel):
    \"\"\"Aggregate output of the Sensitivity agent.\"\"\"

    ruling_id: str
    flips: List[SensitivityFlip] = Field(default_factory=list)
    nearest_flip: Optional[SensitivityFlip] = None
    is_fragile: bool = False
    summary: str = ""
    total_perturbations_tested: int = 0


# ---------------------------------------------------------------------------
# Remediation agent schemas
# ---------------------------------------------------------------------------


class RemediationType(str, Enum):
    \"\"\"Whether a policy-defined waiver path exists.\"\"\"

    WAIVER = "WAIVER"
    SIMULATION = "SIMULATION"


class RemediationStep(BaseModel):
    \"\"\"A single step in a policy-defined waiver process.\"\"\"

    step_number: int
    description: str
    required_approval: Optional[str] = None


class RemediationResult(BaseModel):
    \"\"\"Output of the Remediation agent for a NOT_PERMITTED ruling.\"\"\"

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
    \"\"\"Aggregate output of a corpus scan.\"\"\"

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
    \"\"\"The kind of hypothetical mutation being applied to the policy corpus.\"\"\"

    REMOVE_EXCEPTION = "REMOVE_EXCEPTION"
    ADD_EXCEPTION = "ADD_EXCEPTION"
    MODIFY_RULE = "MODIFY_RULE"
    REMOVE_POLICY = "REMOVE_POLICY"
    ADD_POLICY = "ADD_POLICY"


class SimulationChange(BaseModel):
    \"\"\"Describes a single hypothetical mutation to the policy corpus.\"\"\"

    change_type: SimulationChangeType
    target_policy_id: str
    target_section_id: Optional[str] = None
    new_text: Optional[str] = None
    description: str

    model_config = {"use_enum_values": True}


class SimulationImpact(BaseModel):
    \"\"\"Before/after comparison for a single question under a hypothetical change.\"\"\"

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
    \"\"\"Aggregate output of the Simulation agent.\"\"\"

    simulation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    change: SimulationChange
    total_questions_tested: int = 0
    total_affected: int = 0
    flipped_impacts: List[SimulationImpact] = Field(default_factory=list)
    unaffected_impacts: List[SimulationImpact] = Field(default_factory=list)
    impact_summary: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"use_enum_values": True}
"""

pathlib.Path("schemas.py").write_text(content, encoding="utf-8")
print("Done")
