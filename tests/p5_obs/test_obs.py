import json
import logging

import pytest
from prometheus_client import REGISTRY
from prometheus_client.parser import text_string_to_metric_families

from app.obs.logging import configure_logging
from app.obs.metrics import BUCKETS
from app.obs.setup import setup_observability
from app.obs.tracing import get_provider
from tests.p5_obs.conftest import build_app

CONTRACT_METRICS = {
    "http_requests", "http_request_duration_seconds", "http_requests_in_progress", "db_pool_size",
    "db_pool_checked_out", "db_pool_checkout_wait_seconds", "db_query_duration_seconds",
    "process_cpu_seconds",
}


def sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def request_logs(out: str) -> list[dict]:
    lines = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    return [x for x in lines if x.get("event") == "request"]


def test_metrics_endpoint_has_every_contract_metric(client):
    client.get("/items/1")
    families = {f.name for f in text_string_to_metric_families(client.get("/metrics").text)}
    assert CONTRACT_METRICS <= families


def test_route_label_is_template_never_raw_path(client):
    client.get("/items/1")
    client.get("/items/2")
    client.get("/no-such-path-98765")
    body = client.get("/metrics").text
    assert 'route="/items/{item_id}"' in body
    assert 'route="/items/1"' not in body and "98765" not in body
    assert sample("http_requests_total", method="GET", route="unmatched", status="404") >= 1


def test_metrics_endpoint_does_not_measure_itself(client):
    client.get("/metrics")
    assert 'route="/metrics"' not in client.get("/metrics").text


def test_histogram_buckets_match_contract(client):
    client.get("/items/1")
    les = {s.labels["le"] for f in text_string_to_metric_families(client.get("/metrics").text)
           if f.name == "http_request_duration_seconds" for s in f.samples if s.name.endswith("_bucket")}
    assert {float(x) for x in les} == {*BUCKETS, float("inf")}
    assert BUCKETS == (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)


def test_query_duration_and_checkout_wait_increment_after_db_call(client):
    q0 = sample("db_query_duration_seconds_count", operation="SELECT")
    c0 = sample("db_pool_checkout_wait_seconds_count")
    assert client.get("/items/1").status_code == 200
    assert sample("db_query_duration_seconds_count", operation="SELECT") == q0 + 1
    assert sample("db_pool_checkout_wait_seconds_count") == c0 + 1


def test_pool_gauges_read_pool_at_scrape_time(client, engine):
    assert sample("db_pool_size") == 5
    with engine.connect():
        assert sample("db_pool_checked_out") == 1
    assert sample("db_pool_checked_out") == 0


@pytest.fixture
def stdout_logs(capsys):
    yield lambda: (configure_logging(), capsys)[1]  # must bind inside the test body to see captured stdout
    root = logging.getLogger()  # drop it so background threads never write to a closed capture stream
    root.handlers = [h for h in root.handlers if not getattr(h, "_pulseops", False)]


def test_unhandled_exception_counts_500_and_logs_error_type(client, stdout_logs):
    capsys = stdout_logs()
    n0 = sample("http_requests_total", method="GET", route="/boom", status="500")
    assert client.get("/boom").status_code == 500
    assert sample("http_requests_total", method="GET", route="/boom", status="500") == n0 + 1
    assert sample("http_requests_in_progress") == 0
    [line] = request_logs(capsys.readouterr().out)
    assert line["status"] == 500 and line["error_type"] == "RuntimeError" and line["level"] == "error"


def test_one_request_one_log_line_with_trace_id_and_request_id(client, spans, stdout_logs):
    capsys = stdout_logs()
    spans.clear()
    resp = client.get("/items/1")
    [line] = request_logs(capsys.readouterr().out)
    assert {"ts", "level", "event", "request_id", "trace_id", "span_id", "method", "route",
            "status", "duration_ms"} <= line.keys()
    assert line["route"] == "/items/{item_id}" and line["status"] == 200 and line["ts"].endswith("Z")
    assert resp.headers["x-request-id"] == line["request_id"]
    assert line["trace_id"] in {format(s.context.trace_id, "032x") for s in spans.get_finished_spans()}


def test_one_trace_with_child_db_spans(client, spans):
    spans.clear()
    client.get("/items/1")
    finished = spans.get_finished_spans()
    assert len({s.context.trace_id for s in finished}) == 1
    root = next(s for s in finished if s.parent is None)
    assert root.resource.attributes["service.name"] == "pulseops-api"
    db = [s for s in finished if "db.statement" in s.attributes]
    assert db and all(s.attributes["db.system"] for s in db)
    stmt = db[0].attributes["db.statement"]
    assert "SELECT" in stmt and "'1'" not in stmt  # parameterised text, never values


def test_app_serves_when_otlp_endpoint_is_unreachable(client):
    # conftest points OTLP at a closed port; spans are still being queued for export.
    assert client.get("/items/1").status_code == 200
    get_provider().force_flush(3000)  # must neither raise nor hang
    assert client.get("/items/2").status_code == 200


def test_setup_is_idempotent(engine):
    app = build_app(engine)  # already calls setup once
    setup_observability(app, engine)
    assert sum(getattr(r, "path", "") == "/metrics" for r in app.routes) == 1
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r0 = sample("http_requests_total", method="GET", route="/items/{item_id}", status="200")
    q0 = sample("db_query_duration_seconds_count", operation="SELECT")
    c.get("/items/1")
    assert sample("http_requests_total", method="GET", route="/items/{item_id}", status="200") == r0 + 1
    assert sample("db_query_duration_seconds_count", operation="SELECT") == q0 + 1
