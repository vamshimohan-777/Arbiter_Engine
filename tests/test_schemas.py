"""test_schemas.py — Pydantic model validation tests"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "arbiter", "backend"))

from datetime import date
from schemas import (
    ClauseType,
    RulingDecision,
    PolicySection,
    Policy,
    PolicyContext,
    Citation,
    BlockingClause,
    Ruling,
    CheckerResult,
    ClarificationRequest,
    SensitivityFlip,
    SensitivityResult,
    RemediationType,
    RemediationStep,
    RemediationResult,
    PrecedentStatus,
    CheckerStatus,
    PrecedentMatch,
    PrecedentResult,
    FinalResponse,
)


def test_clause_type_includes_rule():
    """ClauseType.RULE must exist for JSON policy loading."""
    assert ClauseType.RULE == "RULE"


def test_clause_type_all_variants():
    for val in ["PERMISSION", "RESTRICTION", "EXCEPTION", "OVERRIDE",
                "WAIVER", "DEFINITION", "PROCEDURE", "RULE", "OTHER"]:
        ct = ClauseType(val)
        assert ct == val


def test_ruling_decision_enum():
    assert RulingDecision.PERMITTED == "PERMITTED"
    assert RulingDecision.NOT_PERMITTED == "NOT_PERMITTED"
    assert RulingDecision.NEEDS_CLARIFICATION == "NEEDS_CLARIFICATION"


def test_policy_section_optional_policy_id():
    """policy_id should be optional so JSON files don't need to include it."""
    s = PolicySection(section_id="S1", text="Some clause text")
    assert s.policy_id is None
    assert s.clause_type == ClauseType.OTHER


def test_policy_construction():
    p = Policy(
        policy_id="TEST-001",
        version="1.0",
        title="Test Policy",
        effective_date=date(2025, 1, 1),
        sections=[
            PolicySection(section_id="S1", text="Test clause", clause_type=ClauseType.RULE)
        ],
    )
    assert p.policy_id == "TEST-001"
    assert p.is_active is True
    assert len(p.sections) == 1


def test_policy_context_empty():
    ctx = PolicyContext()
    assert ctx.vendor is None
    assert ctx.region is None


def test_checker_result_defaults():
    cr = CheckerResult()
    assert cr.approved is True
    assert cr.objections == []
    assert cr.round_number == 1


def test_clarification_request():
    cr = ClarificationRequest(
        reason="Missing vendor context",
        missing_fields=["vendor"],
        suggested_options={"vendor": ["Vendor X", "Vendor Y"]},
    )
    assert "vendor" in cr.missing_fields
    assert "Vendor X" in cr.suggested_options["vendor"]


def test_ruling_construction():
    import uuid
    r = Ruling(
        ruling_id=str(uuid.uuid4()),
        question="Test question",
        context=PolicyContext(vendor="Vendor X"),
        decision=RulingDecision.NOT_PERMITTED,
        explanation="Vendor X is prohibited.",
        citations=[
            Citation(
                policy_id="VR-001",
                policy_title="Vendor X Policy",
                text_excerpt="Vendor X is prohibited.",
            )
        ],
        relevant_policy_ids=["VR-001"],
    )
    assert r.decision == "NOT_PERMITTED"
    assert len(r.citations) == 1


def test_sensitivity_result():
    flip = SensitivityFlip(
        field="vendor",
        original_value="Vendor X",
        new_value="Vendor Y",
        original_decision=RulingDecision.NOT_PERMITTED,
        new_decision=RulingDecision.PERMITTED,
        explanation="Vendor Y is Tier 1 approved.",
    )
    result = SensitivityResult(
        ruling_id="test-ruling",
        flips=[flip],
        nearest_flip=flip,
        is_fragile=True,
        summary="Ruling flips if vendor changes to Vendor Y.",
        total_perturbations_tested=4,
    )
    assert result.is_fragile is True
    assert result.nearest_flip.field == "vendor"


def test_remediation_waiver():
    step = RemediationStep(
        step_number=1,
        description="Submit Form DGC-EXC-01",
        required_approval="Chief Data Officer",
    )
    result = RemediationResult(
        ruling_id="test-ruling",
        remediation_type=RemediationType.WAIVER,
        is_possible=True,
        steps=[step],
        required_approval="Chief Data Officer",
        supporting_policy_ids=["WAI-DGC-001"],
        supporting_section_ids=["WAIDGC001-S2"],
        explanation="A DGC waiver is available.",
    )
    assert result.remediation_type == "WAIVER"
    assert result.is_possible is True
    assert len(result.steps) == 1


def test_precedent_result_no_match():
    result = PrecedentResult(has_precedent=False)
    assert result.has_precedent is False
    assert result.is_consistent is None
    assert result.status == PrecedentStatus.NO_RELEVANT_PRECEDENT
    assert result.matches == []


def test_precedent_check_unavailable_is_not_consistent():
    result = PrecedentResult(
        has_precedent=True,
        is_consistent=None,
        status=PrecedentStatus.CHECK_UNAVAILABLE,
    )
    assert result.is_consistent is None
    assert result.status == PrecedentStatus.CHECK_UNAVAILABLE


def test_checker_unavailable_is_not_a_pass():
    result = CheckerResult(approved=False, status=CheckerStatus.CHECK_UNAVAILABLE)
    assert result.approved is False
    assert result.status == CheckerStatus.CHECK_UNAVAILABLE
