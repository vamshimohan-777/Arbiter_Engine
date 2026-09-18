import json
import logging
import sqlite3
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Set

import chromadb
from chromadb.config import Settings
from pydantic import BaseModel

from config import settings
from schemas import ClauseType, Policy, PolicyContext, PolicySection

logger = logging.getLogger(__name__)


# Keep every query in this module tied to one explicit column order.  Using
# ``SELECT *`` here is unsafe because an older development database used a
# different order and name for the serialized sections column.
_POLICY_COLUMNS = (
    "policy_id, version, title, effective_date, expiry_date, region, "
    "department, vendor, dataset, category, supersedes, sections_json, "
    "source, is_active"
)


def _key(p: Policy) -> str:
    """Unique key for deduplication."""
    return f"{p.policy_id}:{p.version}"


def _is_in_effect(policy: Policy, as_of: date) -> bool:
    """Check if a policy is active on a given date."""
    if policy.effective_date > as_of:
        return False
    if policy.expiry_date and policy.expiry_date < as_of:
        return False
    return True


class PolicyStore:
    """
    Hybrid datastore for policies:
    1. SQLite for exact metadata filtering and relational lookups (supersessions).
    2. ChromaDB for semantic vector search over clause text.
    """

    def __init__(self) -> None:
        self.db_path = settings.SQLITE_PATH
        self.chroma_path = settings.CHROMA_PATH
        self.collection_name = settings.CHROMA_COLLECTION_NAME
        self.chroma_client: Any = None
        self.collection: Any = None

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create SQLite schema if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT,
                    version TEXT,
                    title TEXT,
                    effective_date DATE,
                    expiry_date DATE,
                    region TEXT,
                    department TEXT,
                    vendor TEXT,
                    dataset TEXT,
                    category TEXT,
                    supersedes TEXT,  -- JSON list
                    sections_json TEXT, -- JSON list of sections
                    source TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (policy_id, version)
                )
                """
            )

            # Migrate databases made by earlier project revisions, which used
            # ``sections`` but later read/write code expected ``sections_json``
            # and lifecycle/source fields.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(policies)")}
            additions = {
                "sections_json": "TEXT",
                "source": "TEXT",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
            }
            for column, definition in additions.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE policies ADD COLUMN {column} {definition}")
            if "sections" in existing:
                conn.execute(
                    "UPDATE policies SET sections_json = sections "
                    "WHERE sections_json IS NULL AND sections IS NOT NULL"
                )
        logger.info("PolicyStore: SQLite tables ready at %s", self.db_path)

    def init_chroma(self) -> None:
        """Connect to local ChromaDB and load the collection."""
        self.chroma_client = chromadb.PersistentClient(
            path=self.chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name
        )
        logger.info(
            "PolicyStore: ChromaDB collection %r ready at %s",
            self.collection_name,
            self.chroma_path,
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_policy(self, policy: Policy) -> None:
        """Save a policy to SQLite and index its sections in ChromaDB."""
        # 1. Save to SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO policies
                (policy_id, version, title, effective_date, expiry_date,
                 region, department, vendor, dataset, category, supersedes, sections_json, source, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.policy_id,
                    policy.version,
                    policy.title,
                    policy.effective_date.isoformat() if policy.effective_date else None,
                    policy.expiry_date.isoformat() if policy.expiry_date else None,
                    policy.region,
                    policy.department,
                    policy.vendor,
                    policy.dataset,
                    policy.category,
                    json.dumps(policy.supersedes),
                    json.dumps([s.model_dump(mode="json") for s in policy.sections]),
                    policy.source,
                    1 if policy.is_active else 0,
                ),
            )

        # 2. Index in ChromaDB
        if not self.collection:
            self.init_chroma()

        docs = []
        metadatas = []
        ids = []

        for sec in policy.sections:
            doc_id = f"{policy.policy_id}::{policy.version}::{sec.section_id}"
            docs.append(sec.text)
            meta = {
                "policy_id": policy.policy_id,
                "title": policy.title,
                "version": policy.version,
                "section_id": sec.section_id,
                "clause_type": sec.clause_type.value if hasattr(sec.clause_type, "value") else str(sec.clause_type),
                "region": policy.region or "",
                "department": policy.department or "",
                "vendor": policy.vendor or "",
                "dataset": policy.dataset or "",
            }
            metadatas.append(meta)
            ids.append(doc_id)

        if ids:
            self.collection.upsert(
                documents=docs,
                metadatas=metadatas,
                ids=ids,
            )

    def load_policies_from_dir(self, directory: str) -> int:
        """Load all JSON policies from a directory into SQLite and ChromaDB."""
        import glob
        import os

        pattern = os.path.join(directory, "*.json")
        files = glob.glob(pattern)
        count = 0

        for fpath in files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                policy = Policy(**data)
                self.save_policy(policy)
                count += 1
            except Exception as exc:
                logger.warning("Failed to load policy %s: %s", fpath, exc)

        logger.info("Loaded %d policies from %s", count, directory)
        return count

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _row_to_policy(self, row: tuple) -> Policy:
        (
            policy_id,
            version,
            title,
            effective_date,
            expiry_date,
            region,
            department,
            vendor,
            dataset,
            category,
            supersedes,
            sections_json,
            source,
            is_active,
        ) = row

        return Policy(
            policy_id=policy_id,
            title=title,
            version=version,
            effective_date=date.fromisoformat(effective_date) if effective_date else date.today(),
            expiry_date=date.fromisoformat(expiry_date) if expiry_date else None,
            region=region,
            department=department,
            vendor=vendor,
            dataset=dataset,
            category=category,
            supersedes=json.loads(supersedes) if supersedes else [],
            source=source,
            is_active=bool(is_active) if is_active is not None else True,
            sections=[PolicySection(**s) for s in (json.loads(sections_json) if sections_json else [])],
        )

    def get_all_active_policies(self, as_of_date: Optional[date] = None) -> List[Policy]:
        """Return all active policies (ignoring supersession here)."""
        d = (as_of_date or date.today()).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
            SELECT """ + _POLICY_COLUMNS + """ FROM policies
                WHERE (effective_date IS NULL OR effective_date <= ?)
                  AND (expiry_date IS NULL OR expiry_date >= ?)
                  AND is_active = 1
                """,
                (d, d),
            )
            return [self._row_to_policy(row) for row in cur.fetchall()]

    def get_policy(self, policy_id: str, version: Optional[str] = None) -> Optional[Policy]:
        """Fetch a specific policy."""
        with sqlite3.connect(self.db_path) as conn:
            if version:
                cur = conn.execute(
                    "SELECT " + _POLICY_COLUMNS + " FROM policies WHERE policy_id = ? AND version = ?",
                    (policy_id, version),
                )
            else:
                cur = conn.execute(
                    "SELECT " + _POLICY_COLUMNS + " FROM policies WHERE policy_id = ? ORDER BY effective_date DESC LIMIT 1",
                    (policy_id,),
                )
            row = cur.fetchone()
            if row:
                return self._row_to_policy(row)
        return None

    def structured_search(
        self,
        context: PolicyContext,
        as_of_date: Optional[date] = None,
        limit: int = 20,
    ) -> List[Policy]:
        """Fetch policies matching explicit metadata context."""
        conditions = ["is_active = 1"]
        params: List[Any] = []

        if context.region:
            conditions.append("(region IS NULL OR region = '' OR region = 'GLOBAL' OR region = ?)")
            params.append(context.region)
        if context.department:
            conditions.append("(department IS NULL OR department = '' OR department = 'ALL' OR department = ?)")
            params.append(context.department)
        if context.vendor:
            conditions.append("(vendor IS NULL OR vendor = '' OR vendor = 'ANY' OR vendor = ?)")
            params.append(context.vendor)
        if context.dataset:
            conditions.append("(dataset IS NULL OR dataset = '' OR dataset = 'ANY' OR dataset = ?)")
            params.append(context.dataset)

        d = (as_of_date or date.today()).isoformat()
        conditions.append("(effective_date IS NULL OR effective_date <= ?) AND (expiry_date IS NULL OR expiry_date >= ?)")
        params.extend([d, d])

        query = f"SELECT {_POLICY_COLUMNS} FROM policies WHERE {' AND '.join(conditions)} LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(query, tuple(params))
            return [self._row_to_policy(row) for row in cur.fetchall()]

    def semantic_search(self, query: str, n_results: int = 5) -> List[Policy]:
        """Query ChromaDB for relevant sections and re-assemble into Policies."""
        if not self.collection:
            return []

        # Chroma rejects requests larger than the current collection.  This
        # happens on a fresh or partially initialized corpus and should not
        # prevent the structured retrieval path from serving a ruling.
        count = self.collection.count()
        if count == 0:
            return []
        n_results = min(n_results, count)

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
        )

        policy_map: Dict[str, Policy] = {}
        if results and results["metadatas"] and results["metadatas"][0]:
            for meta in results["metadatas"][0]:
                pid = meta.get("policy_id")
                ver = meta.get("version")
                if pid and ver:
                    k = f"{pid}:{ver}"
                    if k not in policy_map:
                        p = self.get_policy(str(pid), str(ver))
                        if p:
                            policy_map[k] = p

        return list(policy_map.values())

    # ------------------------------------------------------------------
    # Hybrid Retrieval (Fixed n_results)
    # ------------------------------------------------------------------

    def hybrid_retrieve(
        self,
        question: str,
        context: PolicyContext,
        as_of_date: Optional[date] = None,
        n_results: int = 8,
    ) -> List[Policy]:
        """Combine semantic search and structured filtering. 
        Limits retrieval candidates so context window isn't flooded."""
        
        # 1. Semantic search
        semantic_matches = self.semantic_search(question, n_results=n_results)

        # 2. Structured fetch
        structured_matches = self.structured_search(
            context,
            as_of_date=as_of_date,
            limit=n_results,
        )

        # Merge, deduplicate, and preserve relevance order
        merged_dict: Dict[str, Policy] = {}
        
        for p in semantic_matches:
            if p.policy_id not in merged_dict:
                merged_dict[p.policy_id] = p
                
        for p in structured_matches:
            if p.policy_id not in merged_dict:
                merged_dict[p.policy_id] = p

        final_list = list(merged_dict.values())
        
        logger.info(
            "hybrid_retrieve | semantic=%d structured=%d merged=%d returned=%d",
            len(semantic_matches),
            len(structured_matches),
            len(merged_dict),
            min(len(final_list), n_results),
        )
        
        return final_list[:n_results]

    # ------------------------------------------------------------------
    # Supersession tracking
    # ------------------------------------------------------------------

    def get_supersession_map(self, policies: List[Policy]) -> Dict[str, str]:
        """
        Return a mapping from superseded policy_id -> active policy_id.
        e.g., {'POL-v1': 'POL-v2'}
        """
        mapping: Dict[str, str] = {}
        for active in policies:
            for old_id in active.supersedes:
                mapping[old_id] = active.policy_id
        return mapping
