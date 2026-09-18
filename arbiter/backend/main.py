"""
main.py - Arbiter FastAPI Application
======================================
Clean REST API surface. All routing and business logic live in the
orchestrator and agents — never here.

Endpoints:
  GET  /api/health    — liveness probe
  POST /api/init      — initialize / re-seed the data stores
  POST /api/ask       — core policy ruling endpoint
  POST /api/simulate  — what-if simulation endpoint
  GET  /api/graph     — policy relationship graph
  POST /api/scan      — proactive corpus scan
"""

from __future__ import annotations

import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import date
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from auth import authenticate, clear_session, create_session, current_identity
from orchestrator import ArbiterOrchestrator
from schemas import (
    FinalResponse,
    IdentityContext,
    PolicyContext,
    ScanResult,
    SimulationChange,
    SimulationResult,
)
from stores.graph_store import GraphStore
from stores.policy_store import PolicyStore
from stores.precedent_store import PrecedentStore
from synthetic_demo_inputs import get_ask_demo_inputs

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("arbiter.main")

# ---------------------------------------------------------------------------
# Singletons (module-level, shared across requests)
# ---------------------------------------------------------------------------
policy_store = PolicyStore()
precedent_store = PrecedentStore()
graph_store = GraphStore()
orchestrator: Optional[ArbiterOrchestrator] = None


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global orchestrator
    logger.info("Arbiter starting up …")
    policy_store.init_db()
    policy_store.init_chroma()
    precedent_store.init_db()
    precedent_store.init_chroma()
    graph_store.init_db()

    # A first-run server must be immediately useful.  Previously, startup
    # created empty stores and every query returned no evidence until a user
    # discovered the manual "Initialize / Reload Data" control in the UI.
    if not policy_store.get_all_active_policies():
        policies_count = policy_store.load_policies_from_dir(settings.POLICIES_DIR)
        precedents_file = os.path.join(settings.PRECEDENTS_DIR, "seed_precedents.json")
        precedents_count = (
            precedent_store.load_seed_precedents(precedents_file)
            if os.path.exists(precedents_file)
            else 0
        )
        all_policies = policy_store.get_all_active_policies()
        graph_store.build_from_policies(all_policies)
        logger.info(
            "Seeded fresh Arbiter stores: %d policies, %d precedents, %d graph nodes.",
            policies_count,
            precedents_count,
            len(all_policies),
        )
    orchestrator = ArbiterOrchestrator(policy_store, precedent_store, graph_store)
    logger.info("Arbiter ready.")
    yield
    logger.info("Arbiter shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Arbiter — Agentic Policy Reasoning",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    context: PolicyContext = PolicyContext()
    as_of_date: Optional[date] = None
    session_id: Optional[str] = None


class SimulateRequest(BaseModel):
    change: SimulationChange
    test_questions: Optional[List[str]] = None


class InitResponse(BaseModel):
    status: str
    policies_loaded: int
    precedents_loaded: int
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str


class LoginRequest(BaseModel):
    username: str
    password: str
    vendor: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _check_ready() -> None:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Arbiter not initialized.")


def _attempts_identity_override(question: str, identity: IdentityContext) -> bool:
    """Detect a conflicting claimed identity for a transparent user notice.

    Detection is informational only: trusted context is already constructed
    server-side before the orchestrator is invoked.
    """
    patterns = {
        "vendor": r"\b(?:i am|i'm|use|treat me as)\s+(vendor\s+[\w-]+)",
        "region": r"\b(?:use|treat me as)\s+(india|us|usa|eu|europe)\b",
        "department": r"\b(?:i am|i'm|use|treat me as)\s+(analytics|security|finance|engineering)\b",
    }
    expected = {
        "vendor": identity.vendor,
        "region": identity.region,
        "department": identity.department,
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, question, re.IGNORECASE)
        if match and match.group(1).casefold() != expected[field].casefold():
            return True
    return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health():
    from datetime import datetime
    return HealthResponse(
        status="ok",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.get("/api/demo-inputs")
async def demo_inputs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    feature: Optional[str] = Query(default=None),
):
    """Page through every safe ASK-mode input in the synthetic corpus."""
    return get_ask_demo_inputs(offset=offset, limit=limit, feature=feature)


@app.post("/api/init", response_model=InitResponse)
async def initialize():
    """Load policies, precedents, and build the relationship graph."""
    try:
        # Ensure tables exist
        policy_store.init_db()
        policy_store.init_chroma()
        precedent_store.init_db()
        precedent_store.init_chroma()
        graph_store.init_db()

        # Load policies
        policies_count = policy_store.load_policies_from_dir(settings.POLICIES_DIR)

        # Load precedent seeds
        precedents_file = os.path.join(settings.PRECEDENTS_DIR, "seed_precedents.json")
        prec_count = 0
        if os.path.exists(precedents_file):
            prec_count = precedent_store.load_seed_precedents(precedents_file)

        # Build graph from loaded policies
        all_policies = policy_store.get_all_active_policies(as_of_date=None)
        graph_store.build_from_policies(all_policies)

        msg = (
            f"Loaded {policies_count} policy documents, "
            f"{prec_count} precedents, "
            f"built graph with {len(all_policies)} nodes."
        )
        logger.info(msg)
        return InitResponse(
            status="initialized",
            policies_loaded=policies_count,
            precedents_loaded=prec_count,
            message=msg,
        )
    except Exception as exc:
        logger.exception("Initialization failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Initialization failed: {exc}")


@app.post("/api/auth/login", response_model=IdentityContext)
async def login(request: LoginRequest, response: Response):
    """Create a demo session and return server-verified identity attributes."""
    identity = authenticate(request.username, request.password, request.vendor)
    create_session(response, identity)
    return identity


@app.post("/api/auth/logout", status_code=204)
async def logout(request: Request, response: Response):
    clear_session(request, response)


@app.get("/api/auth/me", response_model=IdentityContext)
async def auth_me(request: Request):
    return current_identity(request)


@app.post("/api/ask", response_model=FinalResponse)
async def ask(request: AskRequest, http_request: Request):
    """Core policy ruling endpoint."""
    _check_ready()
    try:
        identity = current_identity(http_request)
        # The server, not the browser or natural language, controls these
        # attributes.  A request may add auxiliary context only.
        trusted_context = PolicyContext(
            vendor=identity.vendor,
            region=identity.region,
            department=identity.department,
            user_role=identity.role,
            dataset=request.context.dataset,
            additional_context=request.context.additional_context,
        )
        response = await orchestrator.ask(  # type: ignore[union-attr]
            question=request.question,
            context=trusted_context,
            as_of_date=request.as_of_date,
            session_id=request.session_id,
        )
        if _attempts_identity_override(request.question, identity):
            response.ruling.caveats.append(
                "Authenticated policy context is "
                f"{identity.vendor}, {identity.region}, {identity.department}, {identity.role}; "
                "identity cannot be changed from a message."
            )
        return response
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.exception("ASK pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Policy reasoning failed: {exc}")


@app.post("/api/simulate", response_model=SimulationResult)
async def simulate(request: SimulateRequest, http_request: Request):
    """What-if policy change simulation."""
    _check_ready()
    try:
        current_identity(http_request)
        result = await orchestrator.simulate(  # type: ignore[union-attr]
            change=request.change,
            test_questions=request.test_questions,
        )
        return result
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Simulation error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Simulation failed: {exc}")


@app.get("/api/graph")
async def get_graph(policy_id: Optional[str] = Query(default=None)):
    """Return the policy relationship graph in React-Flow format."""
    try:
        if policy_id:
            edges = graph_store.get_edges_for_policy(policy_id)
            node_ids = {e.source_id for e in edges} | {e.target_id for e in edges}
            nodes = [graph_store.get_node(nid) for nid in node_ids]
            nodes = [n for n in nodes if n]
        else:
            data = graph_store.get_graph_for_frontend()
            return data
        return {"nodes": [n.model_dump() if n else {} for n in nodes], "edges": [e.model_dump() for e in edges]}
    except Exception as exc:
        logger.exception("Graph retrieval error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Graph retrieval failed: {exc}")


@app.post("/api/scan", response_model=ScanResult)
async def scan():
    """Proactively scan the policy corpus for conflicts and landmines."""
    _check_ready()
    try:
        result = await orchestrator.scan()  # type: ignore[union-attr]
        return result
    except Exception as exc:
        logger.exception("Scan error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Corpus scan failed: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure we run from the backend directory so relative paths work
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(backend_dir)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
