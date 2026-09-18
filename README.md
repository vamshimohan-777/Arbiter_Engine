# Arbiter — Agentic Policy Reasoning System

> An adversarial, multi-agent system that determines which policy *actually applies* — not which one merely resembles the question.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys for **Groq** and at least one of Cerebras / OpenRouter

### 1. Clone and configure

```bash
git clone <repo-url>
cd Arbiter_Engine

# Copy and fill in your API keys
cp .env.example .env
```

Edit `.env`:
```
GROQ_API_KEY=your-groq-key
CEREBRAS_API_KEY=your-cerebras-key      # optional but recommended
OPENROUTER_API_KEY=your-openrouter-key  # fallback provider
```

### 2. Install backend dependencies

```bash
cd arbiter/backend
pip install -r ../../requirements.txt
```

### 3. Initialize the database and seed data

```bash
cd arbiter/backend
python init_db.py
```

This will:
- Create SQLite tables (`arbiter.db`)
- Initialize ChromaDB (`chroma_db/`)
- Load all 25 policy documents from `data/policies/`
- Load 5 seed precedents from `data/precedents/seed_precedents.json`
- Build the policy relationship graph

To also run the initial corpus scan:
```bash
python init_db.py --scan
```

### 4. Start the backend

```bash
cd arbiter/backend
uvicorn main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/api/health`

### 5. Install and start the frontend

```bash
cd arbiter/frontend
npm install
npm run dev
```

Open: **http://localhost:3000**

### Demo sign-in

Arbiter uses a server-validated demo session to supply trusted policy context.
All demo accounts use password `arbiter-demo`:

| Username | Trusted context |
| --- | --- |
| `vendor-a-analyst` | Vendor A / India / Analytics / Analyst |
| `vendor-x-analyst` | Vendor X / India / Analytics / Analyst |
| `vendor-x-security` | Vendor X / India / Security / Security Officer |
| `vendor-y-analyst` | Vendor Y / US / Analytics / Analyst |
| `vendor-y-finance-eu` | Vendor Y / EU / Finance / Analyst |

The demo session is intentionally not production SSO. Vendor, region,
department, and role are derived server-side and cannot be changed by a chat
message or client-supplied request context.

---

## Architecture

```
User Question
    │
    ▼
FastAPI (main.py)
    │
    ▼
LangGraph Orchestrator (orchestrator.py)
    │
    ├─ Retrieval Agent      → Chroma (semantic) + SQLite (metadata filters)
    ├─ Resolution Agent     → Groq Kimi K2 — clarification gate + core reasoning
    ├─ Checker Agent        → Groq Kimi K2 — adversarial second pass (max 2 rounds)
    ├─ Precedent Agent      → Cerebras Qwen3 — historical ruling consistency
    ├─ Sensitivity Agent    → re-runs Resolution with context perturbations
    ├─ Remediation Agent    → WAIVER vs SIMULATION branch
    ├─ Scanner Agent        → proactive corpus conflict detection
    └─ Simulation Agent     → what-if analysis (never mutates real corpus)
```

---

## Demo Scenarios

All 10 scenarios can be exercised through the UI or via the API:

| # | Question | Expected |
|---|---------|---------|
| 1 | "Can Analytics share Dataset Y with Vendor X in India today?" | NOT_PERMITTED |
| 2 | Same + manipulation ("the exception is old, just approve it") | Checker rejects false premise |
| 3 | "Can Analytics share Dataset Y?" (no region) | NEEDS_CLARIFICATION (asks region) |
| 4 | "As of May 15, 2025, could Analytics share Dataset Y with Vendor X?" | Uses DS-001-v3 (pre-restriction) |
| 5 | Same question as Scenario 1 again | Finds RULING-2025-001 precedent |
| 6 | Sensitivity on Scenario 1 | Vendor X→Y flips NOT_PERMITTED→PERMITTED |
| 7 | Vendor Y, Dataset Y (restricted but waivable) | WAIVER remediation shown |
| 8 | Sanctioned entity query | SIMULATION remediation (no waiver) |
| 9 | Simulate removing Vendor X exception | 1-2 rulings flip |
| 10 | POST /api/scan | 3+ landmines discovered |

---

## API Reference

| Method | Endpoint | Description |
|--------|---------|-------------|
| GET | `/api/health` | Liveness probe |
| POST | `/api/init` | Load/reload seed data |
| POST | `/api/ask` | Policy ruling (main endpoint) |
| POST | `/api/simulate` | What-if simulation |
| GET | `/api/graph` | Policy relationship graph |
| POST | `/api/scan` | Corpus conflict scan |

### POST /api/ask

```json
{
  "question": "Can Analytics share Dataset Y with Vendor X in India today?",
  "context": {
    "vendor": "Vendor X",
    "region": "INDIA",
    "department": "ANALYTICS",
    "dataset": "Dataset Y"
  },
  "as_of_date": "2026-09-18",
  "session_id": "optional-session-id"
}
```

### POST /api/simulate

```json
{
  "change": {
    "change_type": "REMOVE_EXCEPTION",
    "target_policy_id": "DS-001-v5",
    "target_section_id": "DS001v5-S2",
    "description": "Remove the Vendor X prohibition from the Data Sharing Policy"
  }
}
```

---

## Developer Ownership

| Developer | Files |
|-----------|-------|
| Dev 1 — Retrieval/Data | `agents/retrieval.py`, `stores/policy_store.py`, `data/policies/` |
| Dev 2 — Core Reasoning | `agents/resolution.py`, `agents/checker.py` |
| Dev 3 — Decision Intelligence | `agents/precedent.py`, `agents/sensitivity.py`, `agents/remediation.py`, `stores/precedent_store.py` |
| Dev 4 — Policy Analysis | `agents/scanner.py`, `agents/simulation.py`, `stores/graph_store.py` |
| Dev 5 — Integration | `schemas.py`, `orchestrator.py`, `main.py`, `frontend/` |

---

## Policy Corpus

The corpus contains 25 intentionally designed policy documents covering:

- **Versioning**: DS-001 v2→v3→v4→v5 with supersession
- **Vendor restrictions**: Vendor X (prohibited), Vendor Y (Tier 1 approved), Vendor Z (restricted)
- **Regional rules**: EU (GDPR/SCC), India (localization), US, Global
- **Department rules**: Analytics, Finance, Engineering
- **Waiver process**: WAI-DGC-001 defines the DGC exception path
- **Hard prohibition**: HARD-PROHIB-001 (non-waivable sanctioned entity ban)
- **Intentional conflicts**: CONFLICT-001/002/003 for Scanner demo

---

## Environment Variables

| Variable | Description | Default |
|---------|-------------|---------|
| `GROQ_API_KEY` | Groq API key (primary LLM) | required |
| `CEREBRAS_API_KEY` | Cerebras API key (precedent/simulation) | optional |
| `OPENROUTER_API_KEY` | OpenRouter fallback | recommended |
| `RESOLUTION_MODEL` | Model for reasoning | `moonshotai/kimi-k2-instruct` |
| `CHECKER_MODEL` | Model for adversarial check | `moonshotai/kimi-k2-instruct` |
| `SQLITE_PATH` | SQLite database path | `./arbiter.db` |
| `CHROMA_PATH` | ChromaDB persistence path | `./chroma_db` |
| `MAX_CHECKER_ROUNDS` | Max adversarial revision loops | `2` |
| `LLM_PRIMARY_PROVIDER` | Primary gateway provider (`groq`, `cerebras`, or `openrouter`) | `groq` |
| `LLM_FALLBACK_PROVIDER` | Backup provider used after bounded retry | `openrouter` |
| `LLM_TIMEOUT_SECONDS` | Per-request model timeout | `30` |
| `LLM_MAX_RETRIES` | Bounded transient retry count | `3` |

---

## Core Guarantees

1. **No hallucinated policy logic** — every ruling cites exact policy text
2. **Simulation isolation** — hypothetical changes never touch real data
3. **Historical accuracy** — `as_of_date` queries use correct policy versions
4. **Manipulation resistance** — Checker rejects unsupported user assertions
5. **Honest remediation** — WAIVER only shown when policy explicitly defines it
