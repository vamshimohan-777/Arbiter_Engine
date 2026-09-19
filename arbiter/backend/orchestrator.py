"""
orchestrator.py - Arbiter LangGraph Orchestrator
================================================
Owns all routing and state transitions for both ASK and SIMULATE flows.

ASK flow:
  Retrieve → ClarificationGate → Resolve → Check → [Revise → Check]
  → Finalize → Precedent → Sensitivity → [Remediation] → SaveRuling → GetGraph → END

SIMULATE flow:
  SimulationAgent.simulate() → SimulationResult

Policy reasoning lives in agents, not here.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from agents.checker import CheckerAgent
from agents.precedent import PrecedentAgent
from agents.remediation import RemediationAgent
from agents.resolution import ResolutionAgent
from agents.retrieval import RetrievalAgent
from agents.scanner import CorpusScannerAgent
from agents.sensitivity import SensitivityAgent
from agents.simulation import SimulationAgent
from config import settings
from schemas import (
    ClarificationRequest,
    CheckerStatus,
    CheckerResult,
    FinalResponse,
    GraphEdge,
    GraphNode,
    Policy,
    PolicyContext,
    PrecedentStatus,
    PrecedentResult,
    RemediationResult,
    Ruling,
    RulingDecision,
    AnalysisStatus,
    ScanResult,
    SensitivityResult,
    SimulationChange,
    SimulationResult,
    StoredPrecedent,
)
from stores.graph_store import GraphStore
from stores.policy_store import PolicyStore
from stores.precedent_store import PrecedentStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class ArbiterState(TypedDict, total=False):
    # --- Input ---
    question: str
    context: PolicyContext
    as_of_date: date
    session_id: str
    mode: str  # 'ASK' | 'SIMULATE'

    # --- Intermediate ---
    retrieved_policies: List[Policy]
    draft_ruling: Optional[Ruling]
    checker_result: Optional[CheckerResult]
    checker_round: int
    degraded_mode: bool
    clarification: Optional[ClarificationRequest]

    # --- Output ---
    final_ruling: Optional[Ruling]
    precedent_result: Optional[PrecedentResult]
    sensitivity_result: Optional[SensitivityResult]
    remediation_result: Optional[RemediationResult]
    graph_nodes: List[GraphNode]
    graph_edges: List[GraphEdge]

    # --- Plumbing ---
    error: Optional[str]
    start_time: float
    # Agent references (injected by orchestrator)
    _retrieval: Any
    _resolution: Any
    _checker: Any
    _precedent: Any
    _sensitivity: Any
    _remediation: Any
    _graph_store: Any
    _precedent_store: Any


# ---------------------------------------------------------------------------
# Node functions — plain async functions; agents accessed via state
# ---------------------------------------------------------------------------

async def node_retrieve(state: ArbiterState) -> ArbiterState:
    try:
        policies = await state["_retrieval"].retrieve(
            state["question"],
            state["context"],
            state.get("as_of_date"),
        )
        return {**state, "retrieved_policies": policies}
    except Exception as exc:
        logger.error("Retrieval failed: %s", exc)
        return {**state, "retrieved_policies": [], "error": str(exc)}


async def node_clarification_gate(state: ArbiterState) -> ArbiterState:
    try:
        clarification = await state["_resolution"].clarification_gate(
            state["question"],
            state.get("retrieved_policies", []),
            state["context"],
        )
        return {**state, "clarification": clarification}
    except Exception as exc:
        logger.error("Clarification gate failed: %s", exc)
        return {**state, "clarification": None}


async def node_resolve(state: ArbiterState) -> ArbiterState:
    try:
        as_of = state.get("as_of_date") or date.today()
        ruling = await state["_resolution"].resolve(
            state["question"],
            state["context"],
            state.get("retrieved_policies", []),
            as_of,
            is_draft=True,
        )
        return {
            **state,
            "draft_ruling": ruling,
            "checker_round": 0,
            "degraded_mode": ruling.provider_fallback_used or ruling.deterministic,
        }
    except Exception as exc:
        logger.error("Resolution failed: %s", exc)
        return {**state, "error": str(exc)}


async def node_check(state: ArbiterState) -> ArbiterState:
    draft = state.get("draft_ruling")
    if not draft:
        return state
    try:
        round_num = (state.get("checker_round") or 0) + 1
        result = await state["_checker"].check(
            draft,
            state.get("retrieved_policies", []),
            state["question"],
            round_number=round_num,
        )
        return {**state, "checker_result": result, "checker_round": round_num}
    except Exception as exc:
        logger.error("Checker failed: %s", exc)
        # Preserve the core ruling, but never interpret a checker exception as
        # adversarial approval.
        from schemas import CheckerResult, CheckerStatus
        fallback = CheckerResult(
            approved=False,
            status=CheckerStatus.CHECK_UNAVAILABLE,
            explanation="Adversarial verification unavailable.",
            round_number=1,
        )
        return {**state, "checker_result": fallback}


async def node_revise(state: ArbiterState) -> ArbiterState:
    checker = state.get("checker_result")
    draft = state.get("draft_ruling")
    if not checker or not draft:
        return state
    try:
        revised = await state["_resolution"].revise(
            draft,
            checker.objections,
            state.get("retrieved_policies", []),
            state["context"],
        )
        return {**state, "draft_ruling": revised}
    except Exception as exc:
        logger.error("Revision failed: %s", exc)
        # The checker found a real concern, but a rate-limited or unavailable
        # revision service must not make the entire API request fail or start
        # another checker/revision loop.  Preserve the objections and expose
        # the uncertainty honestly when finalizing the original ruling.
        return {
            **state,
            "checker_result": CheckerResult(
                approved=False,
                objections=checker.objections,
                missed_exceptions=checker.missed_exceptions,
                wrong_scope_flags=checker.wrong_scope_flags,
                false_premise_flags=checker.false_premise_flags,
                status=CheckerStatus.CHECK_UNAVAILABLE,
                explanation=(
                    "The checker raised objections, but the revision service "
                    "was unavailable. Review the objections before relying on "
                    "the original ruling."
                ),
                round_number=checker.round_number,
            ),
        }


async def node_finalize(state: ArbiterState) -> ArbiterState:
    draft = state.get("draft_ruling")
    if draft:
        return {**state, "final_ruling": draft}
    return state


async def node_precedent(state: ArbiterState) -> ArbiterState:
    final = state.get("final_ruling")
    if not final:
        return state
    try:
        result = await state["_precedent"].find_precedent(
            state["question"],
            state["context"],
            final,
        )
        return {**state, "precedent_result": result}
    except Exception as exc:
        logger.error("Precedent lookup failed: %s", exc)
        return {
            **state,
            "precedent_result": PrecedentResult(
                has_precedent=False,
                matches=[],
                summary="Historical consistency could not be verified.",
                status=PrecedentStatus.CHECK_UNAVAILABLE,
            ),
        }


async def node_sensitivity(state: ArbiterState) -> ArbiterState:
    final = state.get("final_ruling")
    if not final:
        return state
    try:
        as_of = state.get("as_of_date") or date.today()
        result = await state["_sensitivity"].analyze(
            final,
            state["question"],
            state["context"],
            as_of,
        )
        return {**state, "sensitivity_result": result}
    except Exception as exc:
        logger.error("Sensitivity analysis failed: %s", exc)
        return {
            **state,
            "sensitivity_result": SensitivityResult(
                ruling_id=final.ruling_id,
                flips=[],
                is_fragile=False,
                summary="Sensitivity analysis could not be completed.",
                total_perturbations_tested=0,
                status=AnalysisStatus.CHECK_UNAVAILABLE,
            ),
        }


async def node_remediation(state: ArbiterState) -> ArbiterState:
    final = state.get("final_ruling")
    if not final or final.decision != RulingDecision.NOT_PERMITTED:
        return state
    try:
        result = await state["_remediation"].find_remediation(
            final,
            state.get("retrieved_policies", []),
        )
        return {**state, "remediation_result": result}
    except Exception as exc:
        logger.error("Remediation failed: %s", exc)
        return state


async def node_save_ruling(state: ArbiterState) -> ArbiterState:
    final = state.get("final_ruling")
    if not final:
        return state
    try:
        state["_precedent_store"].save_ruling(final)
    except Exception as exc:
        logger.warning("Could not save ruling to precedent store: %s", exc)
    return state


async def node_get_graph(state: ArbiterState) -> ArbiterState:
    try:
        graph_store = state["_graph_store"]
        nodes = graph_store.get_all_nodes()   # returns List[GraphNode] directly
        edges = graph_store.get_all_edges()   # returns List[GraphEdge] directly
        return {**state, "graph_nodes": nodes, "graph_edges": edges}
    except Exception as exc:
        logger.warning("Graph retrieval failed: %s", exc)
        return {**state, "graph_nodes": [], "graph_edges": []}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_clarification(state: ArbiterState) -> str:
    if state.get("clarification"):
        return "end_clarification"
    return "resolve"


def route_after_resolve(state: ArbiterState) -> str:
    # A fallback-model ruling is still a ruling.  It must receive the same
    # adversarial, precedent, sensitivity, and remediation opportunities as a
    # primary-model ruling.  Each supporting agent has its own bounded linear
    # provider fallback and reports CHECK_UNAVAILABLE when neither provider
    # can complete, rather than silently disappearing from the result.
    return "check"


def route_after_check(state: ArbiterState) -> str:
    checker = state.get("checker_result")
    round_num = state.get("checker_round", 1)
    # Verification availability is independent from the core ruling.  Do not
    # invent a revision loop or claim a pass when the checker is unavailable.
    if checker and checker.status == CheckerStatus.CHECK_UNAVAILABLE:
        return "finalize"
    if checker and not checker.approved and round_num < settings.MAX_CHECKER_ROUNDS:
        return "revise"
    return "finalize"


def route_after_revise(state: ArbiterState) -> str:
    """Avoid rechecking when a revision could not be produced."""
    checker = state.get("checker_result")
    if checker and checker.status == CheckerStatus.CHECK_UNAVAILABLE:
        return "finalize"
    return "check"


def route_after_finalize(state: ArbiterState) -> str:
    final = state.get("final_ruling")
    if final and final.decision == RulingDecision.NOT_PERMITTED:
        return "remediation"
    return "precedent"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _build_ask_graph() -> Any:
    g = StateGraph(ArbiterState)

    g.add_node("retrieve", node_retrieve)
    g.add_node("clarification_gate", node_clarification_gate)
    g.add_node("resolve", node_resolve)
    g.add_node("check", node_check)
    g.add_node("revise", node_revise)
    g.add_node("finalize", node_finalize)
    g.add_node("remediation", node_remediation)
    g.add_node("precedent", node_precedent)
    g.add_node("sensitivity", node_sensitivity)
    g.add_node("save_ruling", node_save_ruling)
    g.add_node("get_graph", node_get_graph)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "clarification_gate")

    g.add_conditional_edges(
        "clarification_gate",
        route_after_clarification,
        {"end_clarification": END, "resolve": "resolve"},
    )

    g.add_conditional_edges(
        "resolve",
        route_after_resolve,
        {"check": "check", "finalize": "finalize"},
    )

    g.add_conditional_edges(
        "check",
        route_after_check,
        {"revise": "revise", "finalize": "finalize"},
    )

    g.add_conditional_edges(
        "revise",
        route_after_revise,
        {"check": "check", "finalize": "finalize"},
    )

    g.add_conditional_edges(
        "finalize",
        route_after_finalize,
        {"remediation": "remediation", "precedent": "precedent", "save_ruling": "save_ruling"},
    )

    g.add_edge("remediation", "precedent")
    g.add_edge("precedent", "sensitivity")
    g.add_edge("sensitivity", "save_ruling")
    g.add_edge("save_ruling", "get_graph")
    g.add_edge("get_graph", END)

    return g.compile()


# ---------------------------------------------------------------------------
# ArbiterOrchestrator
# ---------------------------------------------------------------------------


def _enrich_context_from_question(question: str, context: PolicyContext) -> PolicyContext:
    """If user didn't explicitly fill context fields in UI, extract them from question text."""
    ctx_dict = context.dict()
    q = question

    # Vendor extraction: e.g. "Vendor X", "Vendor Y", "Vendor A"
    if not ctx_dict.get("vendor"):
        m = re.search(r"\b(Vendor\s+[A-Za-z0-9_-]+)\b", q, re.IGNORECASE)
        if m:
            ctx_dict["vendor"] = m.group(1).title()

    # Department extraction
    if not ctx_dict.get("department"):
        m = re.search(r"\b(Analytics|Engineering|Finance|Human Resources|HR|Legal|Security|Procurement)\b", q, re.IGNORECASE)
        if m:
            dept = m.group(1).title()
            if dept.upper() == "HR":
                dept = "HR"
            ctx_dict["department"] = dept

    # Region extraction
    if not ctx_dict.get("region"):
        m = re.search(r"\b(India|US|USA|EU|Europe|Global|UK|Australia|APAC)\b", q, re.IGNORECASE)
        if m:
            reg = m.group(1).upper()
            if reg in ("USA", "US"):
                reg = "US"
            elif reg in ("EUROPE", "EU"):
                reg = "EU"
            elif reg == "INDIA":
                reg = "India"
            elif reg == "AUSTRALIA":
                reg = "Australia"
            ctx_dict["region"] = reg

    # Dataset extraction
    if not ctx_dict.get("dataset"):
        m = re.search(
            r"\b(Dataset\s+[A-Za-z0-9_-]+|customer data|operational logs|employee data|financial records)\b",
            q,
            re.IGNORECASE,
        )
        if m:
            val = m.group(1)
            if val.lower().startswith("dataset"):
                val = val.title()
            elif val.casefold() == "customer data":
                val = "Customer Data"
            ctx_dict["dataset"] = val

    return PolicyContext(**ctx_dict)


class ArbiterOrchestrator:
    """High-level entry point; owns the LangGraph compiled graph and all agents."""

    def __init__(
        self,
        policy_store: PolicyStore,
        precedent_store: PrecedentStore,
        graph_store: GraphStore,
    ) -> None:
        self.policy_store = policy_store
        self.precedent_store = precedent_store
        self.graph_store = graph_store

        self._retrieval = RetrievalAgent(policy_store)
        self._resolution = ResolutionAgent(policy_store)
        self._checker = CheckerAgent(policy_store)
        self._precedent = PrecedentAgent(precedent_store)
        self._sensitivity = SensitivityAgent(policy_store)
        self._remediation = RemediationAgent(policy_store)
        self._scanner = CorpusScannerAgent(policy_store, graph_store)
        self._simulation = SimulationAgent(policy_store, precedent_store)

        self._ask_graph = _build_ask_graph()

    async def ask(
        self,
        question: str,
        context: PolicyContext,
        as_of_date: Optional[date] = None,
        session_id: Optional[str] = None,
    ) -> "FinalResponse":
        """Run the full ASK pipeline and return a FinalResponse."""
        t0 = time.time()
        sid = session_id or str(uuid.uuid4())
        effective_date = as_of_date or date.today()
        enriched_context = _enrich_context_from_question(question, context)

        initial: ArbiterState = {
            "question": question,
            "context": enriched_context,
            "as_of_date": effective_date,
            "session_id": sid,
            "mode": "ASK",
            "retrieved_policies": [],
            "draft_ruling": None,
            "checker_result": None,
            "checker_round": 0,
            "degraded_mode": False,
            "clarification": None,
            "final_ruling": None,
            "precedent_result": None,
            "sensitivity_result": None,
            "remediation_result": None,
            "graph_nodes": [],
            "graph_edges": [],
            "error": None,
            "start_time": t0,
            # Inject agent references so node functions can access them
            "_retrieval": self._retrieval,
            "_resolution": self._resolution,
            "_checker": self._checker,
            "_precedent": self._precedent,
            "_sensitivity": self._sensitivity,
            "_remediation": self._remediation,
            "_graph_store": self.graph_store,
            "_precedent_store": self.precedent_store,
        }

        try:
            final_state: ArbiterState = await self._ask_graph.ainvoke(initial)  # type: ignore[arg-type]
        except Exception:
            # Individual nodes already preserve usable work where possible.
            # This final boundary prevents an unexpected optional-analysis or
            # graph integration failure from turning a policy request into an
            # HTTP 500 response.
            logger.exception("ASK graph failed unexpectedly")
            processing_ms = int((time.time() - t0) * 1000)
            emergency = Ruling(
                ruling_id=str(uuid.uuid4()),
                question=question,
                context=enriched_context,
                decision=RulingDecision.SERVICE_UNAVAILABLE,
                explanation=(
                    "The policy reasoning service is temporarily unavailable. "
                    "No ruling has been issued; please retry shortly."
                ),
                citations=[],
                relevant_policy_ids=[],
                confidence=0.0,
            )
            return _build_response(
                sid, question, enriched_context, emergency, processing_ms=processing_ms
            )

        processing_ms = int((time.time() - t0) * 1000)

        # Clarification short-circuit
        clarification = final_state.get("clarification")
        if clarification:
            # Build a placeholder NEEDS_CLARIFICATION ruling
            placeholder = Ruling(
                ruling_id=str(uuid.uuid4()),
                question=question,
                context=context,
                decision=RulingDecision.NEEDS_CLARIFICATION,
                explanation=clarification.reason,
                citations=[],
                relevant_policy_ids=[],
                confidence=0.0,
            )
            return _build_response(
                sid, question, context, placeholder,
                clarification=clarification,
                processing_ms=processing_ms,
            )

        final_ruling = final_state.get("final_ruling")
        if not final_ruling:
            # Emergency fallback: something went very wrong
            emergency = Ruling(
                ruling_id=str(uuid.uuid4()),
                question=question,
                context=context,
                decision=RulingDecision.SERVICE_UNAVAILABLE,
                explanation=(
                    "The policy reasoning service is temporarily unavailable. "
                    "No ruling has been issued; please retry shortly."
                ),
                citations=[],
                relevant_policy_ids=[],
                confidence=0.0,
            )
            return _build_response(sid, question, context, emergency, processing_ms=processing_ms)

        return _build_response(
            sid,
            question,
            context,
            final_ruling,
            checker_result=final_state.get("checker_result"),
            precedent_result=final_state.get("precedent_result"),
            sensitivity_result=final_state.get("sensitivity_result"),
            remediation_result=final_state.get("remediation_result"),
            graph_nodes=final_state.get("graph_nodes", []),
            graph_edges=final_state.get("graph_edges", []),
            processing_ms=processing_ms,
        )

    async def simulate(
        self,
        change: SimulationChange,
        test_questions: Optional[List[str]] = None,
    ) -> SimulationResult:
        """Run a what-if simulation."""
        return await self._simulation.simulate(change, test_questions)

    async def scan(self) -> ScanResult:
        """Proactively scan the corpus for policy landmines."""
        return await self._scanner.scan()


# ---------------------------------------------------------------------------
# _build_response helper
# ---------------------------------------------------------------------------


def _build_response(
    session_id: str,
    question: str,
    context: PolicyContext,
    ruling: Ruling,
    *,
    clarification: Optional[ClarificationRequest] = None,
    checker_result: Optional[CheckerResult] = None,
    precedent_result: Optional[PrecedentResult] = None,
    sensitivity_result: Optional[SensitivityResult] = None,
    remediation_result: Optional[RemediationResult] = None,
    graph_nodes: Optional[List[GraphNode]] = None,
    graph_edges: Optional[List[GraphEdge]] = None,
    processing_ms: int = 0,
) -> FinalResponse:
    return FinalResponse(
        session_id=session_id,
        question=question,
        context=context,
        ruling=ruling,
        checker_result=checker_result,
        clarification=clarification,
        precedent=precedent_result,
        sensitivity=sensitivity_result,
        remediation=remediation_result,
        graph_nodes=graph_nodes or [],
        graph_edges=graph_edges or [],
        processing_time_ms=processing_ms,
        mode="ASK",
    )
