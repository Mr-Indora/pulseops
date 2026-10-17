"""High-value checks against a RUNNING stack (make up && make seed). The S2 test is last: it
causes a real DB outage, so it must not overlap with the others."""
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_METRICS = [
    "http_requests_total", "http_request_duration_seconds", "http_requests_in_progress",
    "db_pool_size", "db_pool_checked_out", "db_pool_checkout_wait_seconds",
    "db_query_duration_seconds",
]
CONTRACT_ALERTS = {"HighLatencyP95", "HighErrorRate", "DBPoolSaturated", "SlowDBQueries", "APIDown"}


def test_register_login_order_fetch(api, headers):
    products = api.get("/products", params={"limit": 100}).json()
    in_stock = [p for p in products if p["stock"] > 0]
    if not in_stock:
        pytest.skip("no products in stock; run make seed")
    body = {"items": [{"product_id": in_stock[0]["id"], "quantity": 1}]}
    r = api.post("/orders", json=body, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    order = r.json()
    got = api.get(f"/orders/{order['id']}", headers=headers)
    assert got.status_code == 200 and got.json()["id"] == order["id"]


def test_metrics_contract_after_traffic(api, headers):
    api.get("/products")
    api.get("/orders", headers=headers)
    text = api.get("/metrics").text
    missing = [m for m in CONTRACT_METRICS if m not in text]
    assert not missing, f"missing metrics: {missing}"
    # route must be the template, never a raw id (cardinality guard)
    assert not re.search(r'route="[^"]*\d', text)


def test_trace_has_db_child_spans(api, jaeger_url):
    api.get("/products")
    for _ in range(20):  # exporter batches, so poll instead of sleeping once
        try:  # Jaeger takes ~2 s per query on a busy laptop: httpx's 5 s default timeout is too tight
            r = httpx.get(f"{jaeger_url}/api/traces", timeout=20,
                          params={"service": "pulseops-api", "lookback": "5m", "limit": 20})
        except httpx.HTTPError:
            time.sleep(1)
            continue
        for trace in r.json().get("data") or []:
            for span in trace["spans"]:
                tags = {t["key"]: t["value"] for t in span.get("tags", [])}
                if tags.get("db.system") == "postgresql" and span.get("references"):
                    return
        time.sleep(1)
    pytest.fail("no pulseops-api trace with a postgresql child span in the last 5m")


def test_alert_rules_loaded(prom_url):
    groups = httpx.get(f"{prom_url}/api/v1/rules").json()["data"]["groups"]
    names = {rule["name"] for g in groups for rule in g["rules"]}
    assert CONTRACT_ALERTS <= names, f"missing: {CONTRACT_ALERTS - names}"


def test_s2_short_run_passes(api, prom_url, jaeger_url):
    start = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "cli", "run", "S2_db_outage", "--baseline", "20", "--verify", "20"],
        check=False, cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    reports = sorted((ROOT / "reports").glob("*-S2_db_outage"))
    tail = proc.stdout[-1500:] + proc.stderr[-1500:]
    assert reports and reports[-1].stat().st_mtime >= start, tail
    text = (reports[-1] / "report.md").read_text()
    m = re.search(r"Summary[^\n]*\n+.*?\b(PASS|FAIL)\b", text, re.DOTALL)
    assert m and m.group(1) == "PASS", text[:1500]
