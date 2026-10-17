"""Grafana annotations so INJECT/FIX markers show on every dashboard panel (tag: pulseops)."""
from __future__ import annotations

import os
import time

import httpx


def annotate(kind: str, scenario: str, at: float | None = None) -> bool:
    """Best-effort: an unreachable Grafana must never break an experiment."""
    base = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
    body = {"time": int((at or time.time()) * 1000), "tags": ["pulseops", scenario],
            "text": f"{kind} {scenario}"}
    try:
        r = httpx.post(f"{base}/api/annotations", json=body, auth=("admin", "admin"), timeout=5)
        return r.is_success
    except httpx.HTTPError:
        return False
