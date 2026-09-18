"""
graph_store.py — SQLite-backed store for the policy relationship graph.

The graph is a directed multigraph where:
* **Nodes** represent policy documents (one node per policy).
* **Edges** represent semantic relationships between policies
  (supersedes, exception-to, override, conflicts-with, etc.).

The graph is rebuilt from policy metadata on demand and can be exported
in React-Flow-compatible JSON for the front-end visualisation.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from config import settings
from schemas import ClauseType, GraphEdge, GraphNode, Policy, RelationshipType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_NODES_TABLE = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id       TEXT PRIMARY KEY,
    node_type     TEXT NOT NULL DEFAULT 'policy',
    label         TEXT NOT NULL,
    policy_id     TEXT,
    version       TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""

_CREATE_EDGES_TABLE = """
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id           TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL,
    target_id         TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    explanation       TEXT,
    confidence        REAL NOT NULL DEFAULT 1.0,
    source_citation   TEXT
);
"""

# ---------------------------------------------------------------------------
# React-Flow layout constants
# ---------------------------------------------------------------------------

_GRID_COLS = 4
_NODE_WIDTH = 220
_NODE_HEIGHT = 80
_H_GAP = 80
_V_GAP = 120


class GraphStore:
    """Manages the policy relationship graph.

    Usage::

        store = GraphStore()
        policies = policy_store.get_all_active_policies()
        store.clear_and_rebuild(policies)
        graph = store.get_graph_for_frontend()
    """

    def __init__(self) -> None:
        self.init_db()

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(settings.SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=OFF;")   # graph does not enforce FK to policies table
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create graph tables if they do not already exist."""
        with self._get_conn() as conn:
            conn.execute(_CREATE_NODES_TABLE)
            conn.execute(_CREATE_EDGES_TABLE)
        logger.info("GraphStore SQLite tables initialised at %s", settings.SQLITE_PATH)

    # ------------------------------------------------------------------
    # Internal converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            node_id=row["node_id"],
            node_type=row["node_type"],
            label=row["label"],
            policy_id=row["policy_id"],
            version=row["version"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            edge_id=row["edge_id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relationship_type=RelationshipType(row["relationship_type"]),
            explanation=row["explanation"],
            confidence=row["confidence"],
            source_citation=row["source_citation"],
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> None:
        """Insert a new node.  Raises on duplicate node_id."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO graph_nodes
                    (node_id, node_type, label, policy_id, version, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    node.node_id,
                    node.node_type,
                    node.label,
                    node.policy_id,
                    node.version,
                    json.dumps(node.metadata),
                ),
            )

    def upsert_node(self, node: GraphNode) -> None:
        """Insert or update a node by node_id."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO graph_nodes
                    (node_id, node_type, label, policy_id, version, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    node_type     = excluded.node_type,
                    label         = excluded.label,
                    policy_id     = excluded.policy_id,
                    version       = excluded.version,
                    metadata_json = excluded.metadata_json
                """,
                (
                    node.node_id,
                    node.node_type,
                    node.label,
                    node.policy_id,
                    node.version,
                    json.dumps(node.metadata),
                ),
            )

    def add_edge(self, edge: GraphEdge) -> None:
        """Insert a new edge.  Raises on duplicate edge_id."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO graph_edges
                    (edge_id, source_id, target_id, relationship_type,
                     explanation, confidence, source_citation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.edge_id,
                    edge.source_id,
                    edge.target_id,
                    edge.relationship_type
                    if isinstance(edge.relationship_type, str)
                    else edge.relationship_type.value,
                    edge.explanation,
                    edge.confidence,
                    edge.source_citation,
                ),
            )

    def upsert_edge(self, edge: GraphEdge) -> None:
        """Insert or update an edge by edge_id."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO graph_edges
                    (edge_id, source_id, target_id, relationship_type,
                     explanation, confidence, source_citation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET
                    source_id         = excluded.source_id,
                    target_id         = excluded.target_id,
                    relationship_type = excluded.relationship_type,
                    explanation       = excluded.explanation,
                    confidence        = excluded.confidence,
                    source_citation   = excluded.source_citation
                """,
                (
                    edge.edge_id,
                    edge.source_id,
                    edge.target_id,
                    edge.relationship_type
                    if isinstance(edge.relationship_type, str)
                    else edge.relationship_type.value,
                    edge.explanation,
                    edge.confidence,
                    edge.source_citation,
                ),
            )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all_nodes(self) -> List[GraphNode]:
        """Return every node in the graph."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM graph_nodes").fetchall()
            return [self._row_to_node(r) for r in rows]

    def get_all_edges(self) -> List[GraphEdge]:
        """Return every edge in the graph."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM graph_edges").fetchall()
            return [self._row_to_edge(r) for r in rows]

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Return the node with *node_id*, or None if not found."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM graph_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            return self._row_to_node(row) if row else None

    def get_edges_for_policy(self, policy_id: str) -> List[GraphEdge]:
        """Return all edges where either endpoint is a node for *policy_id*.

        Looks up the node_id for the given policy_id first, then fetches
        all edges that touch that node.
        """
        with self._get_conn() as conn:
            node_rows = conn.execute(
                "SELECT node_id FROM graph_nodes WHERE policy_id = ?", (policy_id,)
            ).fetchall()
            if not node_rows:
                return []

            node_ids = [r["node_id"] for r in node_rows]
            placeholders = ",".join("?" * len(node_ids))
            edge_rows = conn.execute(
                f"""
                SELECT * FROM graph_edges
                WHERE source_id IN ({placeholders})
                   OR target_id IN ({placeholders})
                """,
                node_ids + node_ids,
            ).fetchall()
            return [self._row_to_edge(r) for r in edge_rows]

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_from_policies(self, policies: List[Policy]) -> None:
        """Auto-build nodes and edges from a list of Policy objects.

        Node creation
        ~~~~~~~~~~~~~
        One node per policy.  ``node_id`` is set to ``policy_id`` for
        easy cross-referencing.

        Edge creation
        ~~~~~~~~~~~~~
        * **SUPERSEDES** — created for every entry in ``policy.supersedes``.
        * **EXCEPTION_TO** / **OVERRIDE** — created when a policy contains
          a section of type ``EXCEPTION`` or ``OVERRIDE`` that references
          another policy in its metadata (``related_policy_id`` key).
        """
        # Build a lookup of policy_id -> policy for edge-building
        policy_map: Dict[str, Policy] = {p.policy_id: p for p in policies}

        for policy in policies:
            # ---- Node --------------------------------------------------
            meta: Dict[str, Any] = {
                "region": policy.region or "",
                "department": policy.department or "",
                "vendor": policy.vendor or "",
                "dataset": policy.dataset or "",
                "category": policy.category or "",
                "effective_date": policy.effective_date.isoformat() if policy.effective_date else "",
                "expiry_date": policy.expiry_date.isoformat() if policy.expiry_date else "",
                "is_active": policy.is_active,
            }
            node = GraphNode(
                node_id=policy.policy_id,
                node_type="policy",
                label=f"{policy.title} v{policy.version}",
                policy_id=policy.policy_id,
                version=policy.version,
                metadata=meta,
            )
            self.upsert_node(node)

            # ---- SUPERSEDES edges --------------------------------------
            for sup_id in policy.supersedes:
                # Make sure the superseded policy has a node (may not be loaded)
                if sup_id not in policy_map:
                    placeholder = GraphNode(
                        node_id=sup_id,
                        node_type="policy",
                        label=f"Policy {sup_id} (superseded)",
                        policy_id=sup_id,
                        metadata={"is_active": False},
                    )
                    self.upsert_node(placeholder)

                edge = GraphEdge(
                    edge_id=f"supersedes::{policy.policy_id}::{sup_id}",
                    source_id=policy.policy_id,
                    target_id=sup_id,
                    relationship_type=RelationshipType.SUPERSEDES,
                    explanation=f"{policy.title} supersedes {sup_id}",
                    confidence=1.0,
                    source_citation=policy.policy_id,
                )
                self.upsert_edge(edge)

            # ---- EXCEPTION / OVERRIDE edges from section metadata ------
            for section in policy.sections:
                clause_val = (
                    section.clause_type
                    if isinstance(section.clause_type, str)
                    else section.clause_type.value
                )
                if clause_val in (ClauseType.EXCEPTION.value, ClauseType.OVERRIDE.value):
                    related_id = section.metadata.get("related_policy_id")
                    if related_id and isinstance(related_id, str):
                        rel_type = (
                            RelationshipType.EXCEPTION_TO
                            if clause_val == ClauseType.EXCEPTION.value
                            else RelationshipType.OVERRIDE
                        )
                        # Ensure target node exists
                        if related_id not in policy_map:
                            placeholder = GraphNode(
                                node_id=related_id,
                                node_type="policy",
                                label=f"Policy {related_id}",
                                policy_id=related_id,
                            )
                            self.upsert_node(placeholder)

                        edge = GraphEdge(
                            edge_id=f"{clause_val.lower()}::{policy.policy_id}::{related_id}::{section.section_id}",
                            source_id=policy.policy_id,
                            target_id=related_id,
                            relationship_type=rel_type,
                            explanation=section.text[:200],
                            confidence=0.9,
                            source_citation=policy.policy_id,
                        )
                        self.upsert_edge(edge)

        logger.info(
            "GraphStore: built graph with %d nodes and %d edges from %d policies",
            len(self.get_all_nodes()),
            len(self.get_all_edges()),
            len(policies),
        )

    def clear_and_rebuild(self, policies: List[Policy]) -> None:
        """Wipe all nodes and edges, then rebuild from *policies*."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM graph_edges")
            conn.execute("DELETE FROM graph_nodes")
        logger.info("GraphStore: cleared all nodes and edges")
        self.build_from_policies(policies)

    # ------------------------------------------------------------------
    # Front-end export
    # ------------------------------------------------------------------

    def get_graph_for_frontend(self) -> Dict[str, Any]:
        """Return the graph as React-Flow-compatible JSON.

        Node format::

            {
                "id": "<node_id>",
                "type": "default",
                "data": {"label": "<label>", "policy_id": ..., "version": ..., ...},
                "position": {"x": <int>, "y": <int>}
            }

        Edge format::

            {
                "id": "<edge_id>",
                "source": "<source_id>",
                "target": "<target_id>",
                "label": "<relationship_type>",
                "data": {"explanation": ..., "confidence": ..., "source_citation": ...}
            }

        Nodes are laid out in a simple grid.  The front-end may override
        positions using its own auto-layout (e.g. dagre).
        """
        nodes = self.get_all_nodes()
        edges = self.get_all_edges()

        rf_nodes: List[Dict[str, Any]] = []
        for idx, node in enumerate(nodes):
            col = idx % _GRID_COLS
            row = idx // _GRID_COLS
            x = col * (_NODE_WIDTH + _H_GAP)
            y = row * (_NODE_HEIGHT + _V_GAP)

            rf_nodes.append(
                {
                    "id": node.node_id,
                    "type": "default",
                    "data": {
                        "label": node.label,
                        "policy_id": node.policy_id,
                        "version": node.version,
                        "node_type": node.node_type,
                        **node.metadata,
                    },
                    "position": {"x": x, "y": y},
                }
            )

        rf_edges: List[Dict[str, Any]] = []
        for edge in edges:
            rel_label = (
                edge.relationship_type
                if isinstance(edge.relationship_type, str)
                else edge.relationship_type.value
            )
            rf_edges.append(
                {
                    "id": edge.edge_id,
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "label": rel_label,
                    "data": {
                        "explanation": edge.explanation,
                        "confidence": edge.confidence,
                        "source_citation": edge.source_citation,
                    },
                }
            )

        return {"nodes": rf_nodes, "edges": rf_edges}
