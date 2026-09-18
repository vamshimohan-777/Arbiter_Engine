"""
precedent_store.py — Append-only store for past rulings (precedents).

Backends
--------
* **SQLite** — immutable ledger of every ruling that has been issued.
* **ChromaDB** — dense embeddings for semantic similarity search across
  historical decisions.

The store is intentionally append-only: rulings are never modified or
deleted after they are written.  This preserves an auditable history of
all decisions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import chromadb
from chromadb.utils import embedding_functions

from config import settings
from schemas import (
    Citation,
    ClauseType,
    PolicyContext,
    Ruling,
    RulingDecision,
    StoredPrecedent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_PRECEDENTS_TABLE = """
CREATE TABLE IF NOT EXISTS precedents (
    ruling_id              TEXT PRIMARY KEY,
    question               TEXT NOT NULL,
    context_json           TEXT NOT NULL,
    decision               TEXT NOT NULL,
    explanation            TEXT NOT NULL,
    citations_json         TEXT NOT NULL DEFAULT '[]',
    relevant_policy_ids_json TEXT NOT NULL DEFAULT '[]',
    timestamp              TEXT NOT NULL
);
"""


class PrecedentStore:
    """Manages storage and retrieval of past rulings.

    Usage::

        store = PrecedentStore()
        store.save_ruling(ruling, citations)
        similar = store.find_similar_rulings("Can vendor X access dataset Y?", ctx)
    """

    def __init__(self) -> None:
        self._chroma_client: Optional[chromadb.PersistentClient] = None
        self._chroma_collection: Optional[chromadb.Collection] = None
        self._ef: Any = None

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a WAL-mode connection with row_factory set."""
        conn = sqlite3.connect(settings.SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create the precedents table if it does not already exist."""
        with self._get_conn() as conn:
            conn.execute(_CREATE_PRECEDENTS_TABLE)
        logger.info("PrecedentStore SQLite table initialised at %s", settings.SQLITE_PATH)

    # ------------------------------------------------------------------
    # ChromaDB helpers
    # ------------------------------------------------------------------

    def init_chroma(self) -> None:
        """Create or open the ChromaDB collection for precedent embeddings."""
        try:
            import os
            # Use a separate sub-directory to avoid ChromaDB client conflicts
            # with the policy store (which uses CHROMA_PATH directly)
            prec_path = os.path.join(settings.CHROMA_PATH, "precedents")
            os.makedirs(prec_path, exist_ok=True)
            from chromadb.config import Settings as ChromaSettings
            self._chroma_client = chromadb.PersistentClient(
                path=prec_path,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._ef = embedding_functions.DefaultEmbeddingFunction()
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name=settings.CHROMA_PRECEDENT_COLLECTION,
                embedding_function=self._ef,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB precedent collection '%s' ready (%d documents)",
                settings.CHROMA_PRECEDENT_COLLECTION,
                self._chroma_collection.count(),
            )
        except Exception as exc:
            logger.error("Failed to initialise ChromaDB for precedents: %s", exc)
            self._chroma_collection = None

    # ------------------------------------------------------------------
    # Internal converters
    # ------------------------------------------------------------------

    @staticmethod
    def _context_summary(context: PolicyContext) -> str:
        """Build a short textual summary of a PolicyContext for embedding."""
        parts: List[str] = []
        if context.region:
            parts.append(f"region={context.region}")
        if context.department:
            parts.append(f"department={context.department}")
        if context.vendor:
            parts.append(f"vendor={context.vendor}")
        if context.dataset:
            parts.append(f"dataset={context.dataset}")
        if context.user_role:
            parts.append(f"role={context.user_role}")
        return " ".join(parts)

    @staticmethod
    def _citations_to_json(citations: List[Citation]) -> str:
        return json.dumps([c.model_dump() for c in citations])

    @staticmethod
    def _json_to_citations(citations_json: str) -> List[Citation]:
        raw = json.loads(citations_json or "[]")
        result: List[Citation] = []
        for item in raw:
            try:
                result.append(Citation.model_validate(item))
            except Exception as exc:
                logger.warning("Could not parse citation: %s — %s", item, exc)
        return result

    @staticmethod
    def _row_to_stored_precedent(row: sqlite3.Row) -> StoredPrecedent:
        ctx_data = json.loads(row["context_json"] or "{}")
        ctx = PolicyContext.model_validate(ctx_data)
        citations = PrecedentStore._json_to_citations(row["citations_json"])
        rel_ids = json.loads(row["relevant_policy_ids_json"] or "[]")
        return StoredPrecedent(
            ruling_id=row["ruling_id"],
            question=row["question"],
            context=ctx,
            decision=RulingDecision(row["decision"]),
            explanation=row["explanation"],
            citations=citations,
            relevant_policy_ids=rel_ids,
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_ruling(self, ruling: Ruling, citations: Optional[List[Citation]] = None) -> None:
        """Append a ruling to SQLite and embed it in Chroma.

        *citations* may be passed separately when the Ruling object's own
        citations list hasn't been populated yet by a downstream agent.
        """
        effective_citations = citations if citations is not None else ruling.citations

        # ---- SQLite --------------------------------------------------------
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT ruling_id FROM precedents WHERE ruling_id = ?", (ruling.ruling_id,)
            ).fetchone()
            if existing:
                logger.debug("Ruling %s already in SQLite — skipping duplicate write", ruling.ruling_id)
            else:
                conn.execute(
                    """
                    INSERT INTO precedents
                        (ruling_id, question, context_json, decision, explanation,
                         citations_json, relevant_policy_ids_json, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ruling.ruling_id,
                        ruling.question,
                        ruling.context.model_dump_json(),
                        ruling.decision
                        if isinstance(ruling.decision, str)
                        else ruling.decision.value,
                        ruling.explanation,
                        self._citations_to_json(effective_citations),
                        json.dumps(ruling.relevant_policy_ids),
                        ruling.timestamp.isoformat(),
                    ),
                )
                logger.info("Saved ruling %s to SQLite", ruling.ruling_id)

        # ---- Chroma --------------------------------------------------------
        if self._chroma_collection is None:
            return

        doc_text = f"{ruling.question}\n{self._context_summary(ruling.context)}"
        meta: Dict[str, Any] = {
            "ruling_id": ruling.ruling_id,
            "decision": ruling.decision
            if isinstance(ruling.decision, str)
            else ruling.decision.value,
            "vendor": ruling.context.vendor or "",
            "region": ruling.context.region or "",
            "department": ruling.context.department or "",
            "dataset": ruling.context.dataset or "",
            "timestamp": ruling.timestamp.isoformat(),
        }

        try:
            self._chroma_collection.upsert(
                ids=[ruling.ruling_id],
                documents=[doc_text],
                metadatas=[meta],
            )
            logger.debug("Embedded ruling %s in Chroma", ruling.ruling_id)
        except Exception as exc:
            logger.error("Chroma upsert failed for ruling %s: %s", ruling.ruling_id, exc)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_ruling_by_id(self, ruling_id: str) -> Optional[StoredPrecedent]:
        """Retrieve a specific ruling by its ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM precedents WHERE ruling_id = ?", (ruling_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_stored_precedent(row)

    def find_similar_rulings(
        self,
        question: str,
        context: PolicyContext,
        n_results: int = 5,
    ) -> List[StoredPrecedent]:
        """Return the *n_results* most semantically similar past rulings.

        The query is ``question + context summary`` — the same representation
        used when embedding.
        """
        if self._chroma_collection is None:
            logger.warning("Chroma unavailable — returning empty precedent results")
            return []

        count = self._chroma_collection.count()
        if count == 0:
            return []

        n_results = min(n_results, count)
        query_text = f"{question}\n{self._context_summary(context)}"

        try:
            raw = self._chroma_collection.query(
                query_texts=[query_text],
                n_results=n_results,
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            logger.error("Chroma precedent query failed: %s", exc)
            return []

        ruling_ids = [m["ruling_id"] for m in raw["metadatas"][0]]
        results: List[StoredPrecedent] = []
        for rid in ruling_ids:
            sp = self.get_ruling_by_id(rid)
            if sp:
                results.append(sp)
        return results

    def get_all_rulings(self) -> List[StoredPrecedent]:
        """Return every ruling in the store (for simulation / audit purposes)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM precedents ORDER BY timestamp DESC"
            ).fetchall()
            return [self._row_to_stored_precedent(r) for r in rows]

    # ------------------------------------------------------------------
    # Bulk loading
    # ------------------------------------------------------------------

    def load_seed_precedents(self, precedents_file: str) -> int:
        """Load seed precedents from a JSON file.

        The file must contain a JSON array of objects that conform to the
        ``StoredPrecedent`` schema.  Duplicate ruling_ids are silently skipped.

        Returns the number of precedents successfully loaded.
        """
        path = Path(precedents_file) if not isinstance(precedents_file, Path) else precedents_file
        if not path.exists():
            logger.warning("Seed precedents file not found: %s", precedents_file)
            return 0

        try:
            raw_list = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            logger.error("Failed to read seed precedents file %s: %s", precedents_file, exc)
            return 0

        loaded = 0
        for item in raw_list:
            try:
                sp = StoredPrecedent.model_validate(item)
                # Re-hydrate a minimal Ruling for save_ruling
                ruling = Ruling(
                    ruling_id=sp.ruling_id,
                    question=sp.question,
                    context=sp.context,
                    decision=RulingDecision(sp.decision),
                    explanation=sp.explanation,
                    citations=sp.citations,
                    relevant_policy_ids=sp.relevant_policy_ids,
                    timestamp=sp.timestamp,
                )
                self.save_ruling(ruling, sp.citations)
                loaded += 1
            except Exception as exc:
                logger.error("Failed to load seed precedent: %s — %s", item, exc)

        logger.info("PrecedentStore: loaded %d seed precedents from %s", loaded, precedents_file)
        return loaded
