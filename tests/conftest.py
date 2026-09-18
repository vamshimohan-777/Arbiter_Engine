"""conftest.py — shared pytest fixtures for Arbiter tests"""

import os
import sys
import pytest

# Ensure backend is on the path
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "arbiter", "backend")
sys.path.insert(0, BACKEND_DIR)

os.chdir(BACKEND_DIR)


@pytest.fixture(scope="session")
def policy_store(tmp_path_factory):
    """Fresh PolicyStore backed by a temp SQLite + temp Chroma."""
    tmp = tmp_path_factory.mktemp("stores")
    os.environ["SQLITE_PATH"] = str(tmp / "test.db")
    os.environ["CHROMA_PATH"] = str(tmp / "chroma")

    from stores.policy_store import PolicyStore

    store = PolicyStore()
    store.init_db()
    store.init_chroma()
    return store


@pytest.fixture(scope="session")
def precedent_store(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prec")
    os.environ["SQLITE_PATH"] = str(tmp / "test_prec.db")
    os.environ["CHROMA_PATH"] = str(tmp / "chroma_prec")

    from stores.precedent_store import PrecedentStore

    store = PrecedentStore()
    store.init_db()
    store.init_chroma()
    return store
