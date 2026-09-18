"""stores package — exposes the three storage backends for easy import."""

from stores.graph_store import GraphStore
from stores.policy_store import PolicyStore
from stores.precedent_store import PrecedentStore

__all__ = ["PolicyStore", "PrecedentStore", "GraphStore"]
