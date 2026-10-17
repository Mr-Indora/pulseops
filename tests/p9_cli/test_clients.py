import httpx

from cli import grafana
from cli.prom import Prom


def prom_with(handler):
    return Prom("http://p:9090", httpx.Client(transport=httpx.MockTransport(handler)))


def vec(v):
    return httpx.Response(200, json={"status": "success", "data": {"result": [{"value": [1, v]}]}})


def test_instant_nan_and_empty_are_none():
    assert prom_with(lambda r: vec("NaN")).instant("q") is None
    empty = httpx.Response(200, json={"status": "success", "data": {"result": []}})
    assert prom_with(lambda r: empty).instant("q") is None
    assert prom_with(lambda r: vec("0.25")).instant("q", at=5) == 0.25


def test_alerts_returns_alert_list():
    body = {
        "status": "success",
        "data": {"alerts": [{"labels": {"alertname": "A"}, "state": "firing"}]},
    }
    p = prom_with(lambda r: httpx.Response(200, json=body))
    assert p.alerts()[0]["labels"]["alertname"] == "A"


def test_window_queries_use_contract_metrics_and_window():
    queries = []

    def handler(req):
        q = req.url.params["query"]
        queries.append(q)
        if req.url.path.endswith("query_range"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"result": [{"values": [[1, "0.4"], [2, "0.9"]]}]},
                },
            )
        return vec("1")

    w = prom_with(handler).window(1000, 1060)
    assert w["pool_util"] == 0.9 and w["process_restarted"] is True
    joined = "\n".join(queries)
    for name in (
        "http_request_duration_seconds_bucket",
        "http_requests_total",
        "db_pool_checkout_wait_seconds_bucket",
        "process_cpu_seconds_total",
        "process_start_time_seconds",
        "db_pool_checked_out",
        "db_pool_size",
    ):
        assert name in joined
    assert "[60s]" in joined


def test_grafana_annotation_body_and_failure_is_nonfatal(monkeypatch):
    sent = {}

    def ok(url, json, auth, timeout):
        sent.update(url=url, json=json)
        return httpx.Response(200)

    monkeypatch.setattr(grafana.httpx, "post", ok)
    assert grafana.annotate("INJECT", "S4_missing_index", at=10) is True
    assert (
        sent["json"]["tags"][0] == "pulseops" and sent["json"]["text"] == "INJECT S4_missing_index"
    )
    assert sent["url"].endswith("/api/annotations") and sent["json"]["time"] == 10_000

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(grafana.httpx, "post", boom)
    assert grafana.annotate("FIX", "S4") is False
