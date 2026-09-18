#!/usr/bin/env python3
"""
init_db.py - Arbiter Data Initialization Script
================================================
Run this once to set up the database and load all seed data.

Usage:
    cd arbiter/backend
    python init_db.py [--scan]

Options:
    --scan    Also run the initial corpus scan after loading data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings
from stores.graph_store import GraphStore
from stores.policy_store import PolicyStore
from stores.precedent_store import PrecedentStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger("arbiter.init")


def init_stores(
    policy_store: PolicyStore,
    precedent_store: PrecedentStore,
    graph_store: GraphStore,
) -> None:
    """Create all database tables and Chroma collections."""
    logger.info("Initializing SQLite tables …")
    policy_store.init_db()
    precedent_store.init_db()
    graph_store.init_db()

    logger.info("Initializing Chroma collections …")
    policy_store.init_chroma()
    precedent_store.init_chroma()

    logger.info("Stores initialized.")


def load_policies(policy_store: PolicyStore) -> int:
    """Load all policy JSON files from POLICIES_DIR."""
    policies_dir = settings.POLICIES_DIR
    if not os.path.isdir(policies_dir):
        logger.error("Policies directory not found: %s", policies_dir)
        return 0

    count = policy_store.load_policies_from_dir(policies_dir)
    logger.info("Loaded %d policies from %s", count, policies_dir)
    return count


def load_precedents(precedent_store: PrecedentStore) -> int:
    """Load seed precedents from JSON file."""
    seed_file = os.path.join(settings.PRECEDENTS_DIR, "seed_precedents.json")
    if not os.path.exists(seed_file):
        logger.warning("Seed precedents file not found: %s", seed_file)
        return 0

    count = precedent_store.load_seed_precedents(seed_file)
    logger.info("Loaded %d seed precedents", count)
    return count


def build_graph(
    policy_store: PolicyStore,
    graph_store: GraphStore,
) -> int:
    """Build the policy relationship graph from loaded policies."""
    policies = policy_store.get_all_active_policies(as_of_date=None)
    if not policies:
        logger.warning("No policies found — graph will be empty.")
        return 0

    graph_store.build_from_policies(policies)
    logger.info("Built graph with %d policy nodes.", len(policies))
    return len(policies)


async def run_scan(
    policy_store: PolicyStore,
    graph_store: GraphStore,
) -> None:
    """Run the initial corpus scan (optional)."""
    from agents.scanner import CorpusScannerAgent

    logger.info("Running initial corpus scan …")
    scanner = CorpusScannerAgent(policy_store, graph_store)
    result = await scanner.scan()
    logger.info(
        "Scan complete: %d findings, %d landmines. %s",
        len(result.findings),
        len(result.landmines),
        result.summary,
    )
    for lm in result.landmines:
        logger.warning(
            "LANDMINE [%s]: %s vs %s — %s",
            lm.severity,
            lm.policy_id_a,
            lm.policy_id_b,
            lm.description[:100],
        )


async def main(run_corpus_scan: bool = False) -> None:
    # Change to backend directory so relative paths work
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(backend_dir)

    logger.info("=" * 60)
    logger.info("Arbiter Initialization")
    logger.info("  SQLITE_PATH  : %s", settings.SQLITE_PATH)
    logger.info("  CHROMA_PATH  : %s", settings.CHROMA_PATH)
    logger.info("  POLICIES_DIR : %s", settings.POLICIES_DIR)
    logger.info("  PRECEDENTS_DIR: %s", settings.PRECEDENTS_DIR)
    logger.info("=" * 60)

    policy_store = PolicyStore()
    precedent_store = PrecedentStore()
    graph_store = GraphStore()

    # Step 1: Init stores
    init_stores(policy_store, precedent_store, graph_store)

    # Step 2: Load policies
    n_policies = load_policies(policy_store)

    # Step 3: Load precedents
    n_precedents = load_precedents(precedent_store)

    # Step 4: Build graph
    n_nodes = build_graph(policy_store, graph_store)

    # Step 5: Optional scan
    if run_corpus_scan:
        await run_scan(policy_store, graph_store)

    logger.info("=" * 60)
    logger.info("Initialization complete.")
    logger.info("  Policies loaded : %d", n_policies)
    logger.info("  Precedents loaded: %d", n_precedents)
    logger.info("  Graph nodes     : %d", n_nodes)
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize Arbiter data stores.")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Run initial corpus scan after loading data.",
    )
    args = parser.parse_args()
    asyncio.run(main(run_corpus_scan=args.scan))
