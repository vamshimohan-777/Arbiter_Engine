"""Read-only catalog of safe ASK-mode inputs from the synthetic corpus.

The benchmark's expected decisions and gold citations intentionally remain in
the source archive and are never returned by this module.  They must not be
shown to the model while users are evaluating policy reasoning.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from config import settings


def _queries_path() -> Path:
    return Path(settings.SYNTHETIC_DATA_DIR) / "queries.jsonl.gz"


def _records() -> Iterator[Dict[str, Any]]:
    path = _queries_path()
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                yield json.loads(line)


def get_ask_demo_inputs(
    *, offset: int = 0, limit: int = 25, feature: Optional[str] = None
) -> Dict[str, Any]:
    """Return one page of synthetic ASK inputs without benchmark answers."""
    offset = max(0, offset)
    limit = max(1, min(limit, 100))
    selected = 0
    items = []
    features = set()

    for record in _records():
        record_feature = str(record.get("feature", "uncategorized"))
        features.add(record_feature)
        if feature and record_feature != feature:
            continue
        if selected < offset:
            selected += 1
            continue
        if len(items) >= limit:
            continue

        raw_context = record.get("context") or {}
        context = {
            key: raw_context[key]
            for key in ("region", "department", "vendor")
            if raw_context.get(key) is not None
        }
        # The synthetic corpus calls this data_type; Arbiter's request
        # contract calls it dataset.
        if raw_context.get("data_type"):
            context["dataset"] = raw_context["data_type"]

        items.append(
            {
                "case_id": record.get("case_id"),
                "feature": record_feature,
                "difficulty": record.get("difficulty"),
                "question": record.get("question"),
                "context": context,
                "as_of_date": raw_context.get("as_of_date"),
            }
        )
        selected += 1

    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + len(items) if len(items) == limit else None,
        "available_features": sorted(features),
        "source": "Arbiter Synthetic Policy Reasoning Corpus v1.0",
        "notice": (
            "Use these as ASK-mode inputs only. Benchmark expected decisions "
            "and gold citations are intentionally not exposed."
        ),
    }
