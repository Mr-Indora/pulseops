"""Jaeger trace sampling and the Section-6 trace evidence (db_time_share etc.)."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

import httpx

ERR_TEXT = re.compile(r"OperationalError|connection (refused|reset|closed)|psycopg", re.I)


def fetch_traces(start: float, end: float, url: str | None = None, limit: int = 200) -> list[dict]:
    base = (url or os.environ.get("JAEGER_URL", "http://localhost:16686")).rstrip("/")
    params = {"service": "pulseops-api", "start": int(start * 1e6), "end": int(end * 1e6),
              "limit": limit}  # bounded sample: Jaeger returns the newest `limit` traces
    r = httpx.get(f"{base}/api/traces", params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("data") or []


def _tags(span: dict) -> dict:
    return {t["key"]: t["value"] for t in span.get("tags", [])}


def analyze(traces: list[dict]) -> dict:
    """db_time_share = sum(db statement span time) / sum(root span time);
    top_statement_share = share of total db time owned by the statement with the highest MEAN
    duration (a uniform slowdown, where every statement is slow, must not look like one hot query);
    db_error_spans = error spans whose exception is a connection failure (OperationalError/refused/reset)."""
    root_us = 0
    by_stmt: dict[str, list[int]] = defaultdict(list)
    errors = 0
    for trace in traces:
        spans = trace.get("spans", [])
        roots = [s for s in spans if not s.get("references")]
        if not roots or any("/metrics" in s.get("operationName", "") for s in roots):
            continue  # Prometheus scrapes are not user traffic
        root_us += sum(s["duration"] for s in roots)
        for s in spans:
            tags = _tags(s)
            if "db.statement" in tags:
                by_stmt[tags["db.statement"]].append(s["duration"])
            # Only real connection failures count: a QueuePool timeout is also an error span with
            # db.system, but it means "pool exhausted", not "DB unreachable".
            if tags.get("error") in (True, "true") and ERR_TEXT.search(json.dumps(s.get("logs", []))):
                errors += 1
    db_us = sum(sum(d) for d in by_stmt.values())
    top = max(by_stmt.values(), key=lambda d: sum(d) / len(d), default=None)
    return {
        "db_time_share": db_us / root_us if root_us else None,
        "top_statement_share": sum(top) / db_us if top and db_us else None,
        "db_error_spans": errors if root_us else None,
        "traces_sampled": len(traces),
    }
