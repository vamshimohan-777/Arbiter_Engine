# Arbiter

## 1\. Team Details

**Team Name / ID:** Arbiter Engine

**Team Lead:** Vamshi Mohan Kasivajhula

**Team Members:**

- Vamshi Mohan Kasivajhula | Backend Developer & Agent Whisperer

**Repo Link (Optional):** N/A

**Demo Link (Optional):** N/A

---

## 2\. Problem Statement

<!-- Paste the full problem statement exactly as it was given to you. Don't shorten, fix, or reword anything. No character limit here. -->

P5 — The Company That Forgot What Its Own Policies Said

A mid-size company has accumulated hundreds of internal policies over the years — data sharing agreements, vendor restrictions, regional compliance rules, departmental approvals, and more. These policies have been updated, versioned, partially superseded, and occasionally contradicted each other without anyone noticing.

When employees need to make a decision — "can we share Dataset Y with Vendor X?" — they ask the internal knowledge system. The knowledge system searches the policy corpus, finds something that looks relevant, and returns it. But "relevant" and "applicable" are not the same thing.

The knowledge system does not know:
- That the policy it found was superseded six months ago by a stricter version.
- That an exception exists, but only for a different department.
- That two policies directly contradict each other and no one has noticed.
- That the ruling it's about to give was already given differently in a similar case last year.

Employees make decisions based on outdated, inapplicable, or outright wrong information. Compliance incidents follow. Audits find problems. Nobody can explain why a decision was made.

Build a system that actually determines which policy applies — not just which one matches.

---

## 3\. TL;DR

**Problem:** Policy retrieval returns "relevant" docs but can't determine which policy actually applies.

**Solution:** Multi-agent LangGraph pipeline that reasons over versions, conflicts, precedents, and exceptions.

**Who benefits:** Compliance teams, data governance officers, and any employee needing a defensible policy ruling.

---

## 4\. Scope of the Project

**What are you building?**

Arbiter: a FastAPI + LangGraph system with 8 specialized agents (Retrieval, Resolution, Checker, Precedent, Sensitivity, Remediation, Scanner, Simulation) that determines which policy actually applies by reasoning over versioning, supersession, scope, exceptions, conflicts, and historical rulings.

**How does it solve the problem statement?**

Instead of returning matching documents, Arbiter issues a structured ruling with the exact blocking clause, citations, a precedent consistency check, a sensitivity analysis, and a remediation path — all grounded in the actual policy corpus.

**Key features you're building for this hackathon:**

- Policy-version-aware rulings: the correct version is applied based on effective/expiry dates
- Adversarial self-check: a second LLM pass rejects false premises and missed exceptions
- Sensitivity analysis: identifies the nearest context change that would flip the ruling
- Remediation paths: shows waiver steps (when policy permits) or simulation-only (when non-waivable)
- Proactive corpus scanning: detects policy contradictions and conflicts without being asked

**What are you deliberately NOT doing?**

No Kubernetes, Redis, Kafka, or microservices. No multi-tenant auth. No real-time streaming of LLM tokens. Frontend is functional but minimal — the reasoning engine is the product.

---

## 5\. Why an Agentic Approach?

**What does your agent decide or do on its own?**

The orchestrator routes between up to 8 agents dynamically based on state: it gates on clarification need, loops the checker for up to 2 revision rounds, branches remediation to WAIVER or SIMULATION based on whether the blocking clause is waivable, and only runs sensitivity analysis when a concrete ruling was reached (not on clarifications).

**Why wouldn't a fixed script, if-else rules, or a simple chatbot be enough?**

Policy applicability requires multi-step reasoning: version selection, scope matching, exception checking, adversarial self-review, and precedent comparison — none of which is a lookup. A chatbot returns text. Arbiter returns a structured, falsifiable ruling with citations. An if-else tree cannot generalize across a corpus of 25+ policies with overlapping scopes and intentional contradictions.

---

## 6\. Who It's For & What Changes

**Who or what is this for?**

Internal compliance officers, data governance teams, and employees requesting data-sharing approvals at mid-to-large companies.

**The world today, without your solution:**

Employees query a keyword search or RAG system, get the most similar document (which may be superseded, wrong-scoped, or contradicted by another policy), and make decisions based on it. Compliance incidents only surface at audit time. Nobody can trace why a decision was made or what policy applied on a given date.

**The world with your solution, fully built and scaled to production:**

Every policy question returns a structured ruling with the applicable policy version, exact blocking clause, adversarially-verified reasoning, and an audit-ready trail. Compliance teams get proactive alerts when new policies conflict with existing ones. Historical queries reconstruct which policy applied on any past date.

**What your hackathon build actually delivers today:**

A working FastAPI backend with 8 functional agents, 24 real policy documents (versioned, scoped, with intentional conflicts), SQLite + ChromaDB storage, a Next.js frontend, and a `/api/health` endpoint verified live. The `/api/ask` endpoint invokes the full LangGraph pipeline; actual LLM calls require user-provided API keys.

**Before vs. After**

| What Changes | Today | With Our Current Build | At Production Scale |
| :---- | :---- | :---- | :---- |
| Time to resolve a data-sharing question | Hours of manual policy search | Seconds via `/api/ask` (with API keys) | Under 5 seconds per ruling |
| Confidence in ruling correctness | None — no cross-check | Adversarial checker catches false premises | 2-round self-check + precedent consistency |
| Policy conflict detection | Found at audit, months later | Proactive via `/api/scan` | Real-time on every new policy upload |
| Historical ruling traceability | Not possible | `as_of_date` param reconstructs applicable version | Full audit log with citation trail |

---

## 7\. Architecture & Agents

**How is your system put together?**

User submits a question + context (vendor, region, department, dataset) to FastAPI. The LangGraph orchestrator runs up to 8 agents in sequence/parallel, returns a structured FinalResponse with ruling, citations, checker result, sensitivity analysis, precedent match, and remediation path. A Next.js frontend renders the result.

### 7.1 Agents

- **Retrieval Agent:** Builds a hybrid semantic + metadata query, calls ChromaDB + SQLite, filters for the correct policy version by effective date. Uses Groq llama-3.1-8b-instant (fast, sufficient for retrieval). Talks to PolicyStore.
- **Resolution Agent:** Takes retrieved policies, applies clarification gate, issues a structured Ruling (PERMITTED / NOT_PERMITTED / NEEDS_CLARIFICATION) with blocking clause and citations. Uses Groq moonshotai/kimi-k2-instruct (strongest reasoning). Talks to orchestrator state.
- **Checker Agent:** Adversarially reviews the Ruling: checks for false premises in user question, missed exceptions, wrong scope, and manipulation. Can trigger a revision loop up to 2 rounds. Uses Groq moonshotai/kimi-k2-instruct. Talks to Resolution Agent via orchestrator.
- **Precedent Agent:** Searches historical rulings in ChromaDB for similar past decisions and assesses consistency. Flags discrepancies. Uses Cerebras qwen-3-32b (fast inference, no JSON mode needed). Talks to PrecedentStore.
- **Sensitivity Agent:** Perturbs vendor/region/department/dataset context and re-runs Resolution to find the nearest flip. Identifies ruling fragility. Uses same model as Resolution. Talks to PolicyStore and ResolutionAgent.
- **Remediation Agent:** When a ruling is NOT_PERMITTED, finds whether the blocking clause is waivable. If yes, returns the DGC waiver steps. If no, returns a SIMULATION prompt. Uses Groq kimi-k2. Talks to PolicyStore.
- **Scanner Agent:** Scans all policies deterministically for supersession, scope overlap, and then uses LLM for semantic conflicts. Writes GraphEdges for detected conflicts. Uses Groq llama-3.1-8b-instant. Talks to PolicyStore and GraphStore.
- **Simulation Agent:** Deep-copies the policy corpus, applies a hypothetical change, re-runs Resolution on test questions, and reports which rulings flipped. Never writes to real stores. Uses Cerebras qwen-3-32b. Talks to PolicyStore (read-only copy).

### 7.2 Services, APIs, Databases & Memory

- **PolicyStore (SQLite + ChromaDB):** Stores 24 policy documents. SQLite for metadata filters; ChromaDB for semantic retrieval. Used by Retrieval, Resolution, Checker, Remediation, Scanner, Simulation.
- **PrecedentStore (SQLite + ChromaDB):** Append-only store for past rulings. SQLite for structured access; ChromaDB for similarity search. Used by Precedent Agent.
- **GraphStore (SQLite):** Policy relationship graph: supersession, conflicts, exceptions. Used by Scanner and frontend graph view.
- **Groq API:** Primary LLM provider for Resolution, Checker, Retrieval, Scanner, Remediation agents.
- **Cerebras API:** Used for Precedent and Simulation agents (fast inference, no JSON-mode overhead).
- **OpenRouter API:** Fallback for all agents when primary providers fail or rate-limit.
- **Next.js Frontend:** Chat interface with verdict cards, citation list, sensitivity badge, remediation panel, React Flow reasoning graph, and simulation panel.

**How does your system remember things (memory & state)?**

LangGraph maintains full pipeline state within a single request (TypedDict ArbiterState). Rulings are saved to PrecedentStore (SQLite + ChromaDB) after every successful resolution, creating a persistent precedent history used by future calls.

**Diagram Link (Optional):** N/A

### 7.3 Example Walkthrough

**Example input:** "Can Analytics share Dataset Y with Vendor X in India today?"

1. [FastAPI] Receives POST /api/ask with context: vendor=Vendor X, department=ANALYTICS, dataset=Dataset Y, region=INDIA
2. [Retrieval Agent] Runs hybrid search — ChromaDB semantic query + SQLite filter for active policies — returns DS-001-v5, VR-001, REG-INDIA-001, DEPT-ANALYTICS-001 (uses: PolicyStore)
3. [Resolution Agent] Reads all 4 policies; finds DS-001-v5-S1 hard prohibition on Vendor X; issues NOT_PERMITTED ruling with blocking clause citation (uses: Groq kimi-k2)
4. [Checker Agent] Reviews: confirms Vendor X prohibition is current version, checks if user question contained false premises (none found), approves ruling (uses: Groq kimi-k2)
5. [Precedent Agent] Finds RULING-2025-001 — same question, same NOT_PERMITTED — flags consistency confirmed (uses: Cerebras qwen-3-32b, PrecedentStore)
6. [Sensitivity Agent] Perturbs vendor to Vendor Y → ruling flips to PERMITTED; sets is_fragile=True, nearest_flip = vendor:Vendor X→Vendor Y
7. [Remediation Agent] Reads DS-001-v5-S1: "This restriction may not be waived" → returns SIMULATION type, no waiver path
8. [GraphStore] Fetches policy relationship nodes and edges for frontend graph rendering

**Final output:** NOT_PERMITTED verdict with blocking clause, RULING-2025-001 precedent match, fragile ruling warning (flip on vendor change), and a "Explore policy change" button (no waiver possible).

**Anything special about how your workflow runs?**

The Checker runs in a bounded loop (max 2 rounds): if it rejects the ruling, Resolution revises once, then Checker runs again. On the second rejection or any runtime error, the loop breaks and the best available ruling is returned. This prevents infinite loops while maintaining adversarial quality.

---

## 8\. Tech Stack

| Layer | Technology |
| :---- | :---- |
| Frontend / Interface | Next.js 14 (App Router), Tailwind CSS, @xyflow/react |
| Backend | Python 3.11+, FastAPI, uvicorn |
| Agent Framework | LangGraph 0.2+, LangChain Core |
| Database / Storage | SQLite (structured metadata), ChromaDB (semantic vectors) |
| Hosting | Local machine (no cloud deployment for this submission) |
| Other | Groq API (primary LLM), Cerebras API (precedent/sim), OpenRouter (fallback) |

---

## 9\. What to Expect From Our Current Build

**Working:**

- FastAPI backend starts and serves `/api/health` (verified live: returns `{"status":"ok"}`)
- All 8 agent classes are fully implemented with real LLM call logic (not mocked)
- SQLite + ChromaDB stores initialize, accept 24 policy documents, and 5 seed precedents
- LangGraph orchestrator with full state machine: clarification gate, checker loop, routing
- Policy corpus: 24 JSON documents covering versioning, supersession, regional rules, conflicts
- `init_db.py` initializes all stores from scratch in one command
- Next.js frontend with all components: verdict card, citation list, sensitivity badge, remediation panel, React Flow reasoning graph, simulation panel
- `python -m uvicorn main:app --port 8000` starts and the server accepts requests

**Partly working, mocked, or hard-coded:**

- `/api/ask` pipeline is fully wired but requires user-provided Groq/Cerebras API keys in `.env` — without keys the agents return errors (clients initialize with "placeholder" but actual LLM calls fail)
- Frontend npm install has not been run — requires `npm install` in `arbiter/frontend/` before use
- Simulation agent test questions are generic when none are provided; more targeted defaults would improve demo quality

**Not working or not built yet:**

- No production deployment (no cloud hosting, no SSL)
- No authentication or multi-user session isolation
- Automated test suite: test files exist (conftest.py) but tests are not complete
- `/api/scan` LLM-based conflict detection requires API keys to surface semantic conflicts (deterministic scan still runs)

**What we'd most like to be judged on:**

The multi-agent reasoning pipeline design: the adversarial checker loop, the sensitivity analysis that finds the nearest ruling flip, the remediation branching (waivable vs. non-waivable), and the corpus with intentional conflicts designed to exercise all edge cases.

---

## 10\. Future Scope

### Idea 1

**Name:** Policy Upload & Versioning API

**What it is:** An endpoint that accepts a new policy document, validates it, assigns a version, detects supersession of older versions, and immediately triggers an incremental corpus scan for new conflicts.

**Why it matters:** The current corpus is static. Real organizations add and update policies constantly. This closes the loop between policy authorship and automated compliance checking.

**How we'd build it:** POST `/api/policies` endpoint, extend PolicyStore with version conflict detection, trigger CorpusScannerAgent on upload, emit webhook events for new conflicts.

**Done when:** Upload a new policy that supersedes DS-001-v5, verify old version is no longer returned, and verify the scanner detects any new conflicts introduced.

### Idea 2

**Name:** Audit Trail & Explainability Report

**What it is:** A structured PDF/Markdown report for any ruling, showing the full reasoning chain: which policies were considered and eliminated, why the blocking clause was selected, how the checker revised the ruling, and which precedents matched.

**Why it matters:** Compliance teams need a paper trail for audits. "The AI said no" is not sufficient. An explainability report turns each ruling into a defensible document.

**How we'd build it:** Extend FinalResponse with an `audit_chain` field, add a `/api/ruling/{ruling_id}/report` endpoint, generate Markdown or PDF using the stored state.

**Done when:** A ruling for "Vendor X + Dataset Y" generates a downloadable report that a compliance officer can file in an audit folder.

### Idea 3 (Optional)

**Name:** Historical Policy Reconstruction

**What it is:** Given any past date and a question, reconstruct exactly which policies were in effect on that date and issue the ruling that would have applied then — useful for retroactive compliance audits.

**Why it matters:** "What should have been decided on March 15, 2025?" is a real audit question. Current RAG systems cannot answer it.

**How we'd build it:** `as_of_date` parameter is already wired into `/api/ask` and PolicyStore's date filtering. Need to add a `policy_timeline` view showing version history per policy ID, and validate that the correct version is selected for any historical date.

**Done when:** Query "Can Analytics share Dataset Y with Vendor X?" with `as_of_date=2025-03-15` returns PERMITTED (pre-prohibition), and `as_of_date=2026-07-01` returns NOT_PERMITTED (post-prohibition).

---

## 11\. Additional Notes (Optional)

Developer ownership for the 5-developer team model described in the README:
Dev 1 (Retrieval/Data): `agents/retrieval.py`, `stores/policy_store.py`, `data/policies/`
Dev 2 (Core Reasoning): `agents/resolution.py`, `agents/checker.py`
Dev 3 (Decision Intelligence): `agents/precedent.py`, `agents/sensitivity.py`, `agents/remediation.py`, `stores/precedent_store.py`
Dev 4 (Policy Analysis): `agents/scanner.py`, `agents/simulation.py`, `stores/graph_store.py`
Dev 5 (Integration): `schemas.py`, `orchestrator.py`, `main.py`, `frontend/`

&nbsp;
