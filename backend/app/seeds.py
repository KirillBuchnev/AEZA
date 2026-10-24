"""Source of data for an empty database: the case dataset, the synthetic demo or nothing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .risk import demo_snapshot
from .schemas import SnapshotUpload

CASE_SNAPSHOT = Path(__file__).resolve().parent / "seeds" / "case_snapshot.json"
SEED_NAMES = ("case", "demo", "empty")


def seed_customers(seed: str) -> list[dict[str, Any]] | None:
    """Return normalized customers for the chosen seed, or None for an empty start."""
    if seed == "empty":
        return None
    if seed == "demo":
        return demo_snapshot()
    if seed == "case":
        payload = SnapshotUpload.model_validate(json.loads(CASE_SNAPSHOT.read_text(encoding="utf-8")))
        return [customer.model_dump(mode="json") for customer in payload.customers]
    raise ValueError(f"AEZA_SEED must be one of {', '.join(SEED_NAMES)}.")
