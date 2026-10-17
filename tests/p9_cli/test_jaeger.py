import httpx

from cli import jaeger


def span(sid, dur, parent=None, op="GET /x", tags=None, logs=None):
    return {
        "spanID": sid,
        "operationName": op,
        "duration": dur,
        "references": [{"refType": "CHILD_OF", "spanID": parent}] if parent else [],
        "tags": [{"key": k, "value": v} for k, v in (tags or {}).items()],
        "logs": logs or [],
    }


def trace(root_dur, *db):
    spans = [span("r", root_dur)]
    for i, (stmt, dur) in enumerate(db):
        spans.append(
            span(f"d{i}", dur, "r", "SELECT", {"db.system": "postgresql", "db.statement": stmt})
        )
    return {"spans": spans}


def test_one_dominant_statement():
    r = jaeger.analyze([trace(1000, ("SELECT slow", 800), ("SELECT fast", 10)) for _ in range(5)])
    assert r["db_time_share"] == 0.81
    assert round(r["top_statement_share"], 3) == round(800 / 810, 3)
    assert r["db_error_spans"] == 0 and r["traces_sampled"] == 5


def test_uniform_slowdown_is_not_one_hot_statement():
    traces = [trace(1000, (f"SELECT {i}", 200)) for i in range(4)] * 3
    assert jaeger.analyze(traces)["top_statement_share"] == 0.25


def test_metrics_scrapes_and_empty_input_give_none_not_zero():
    scrape = {"spans": [span("r", 500, op="GET /metrics")]}
    r = jaeger.analyze([scrape])
    assert (
        r["db_time_share"] is None
        and r["top_statement_share"] is None
        and r["db_error_spans"] is None
    )
    assert jaeger.analyze([])["db_time_share"] is None


def test_error_spans_counted():
    # A pool timeout is an error DB span too, but it is NOT a connection failure (found in S1).
    pool_timeout = span("d", 5, "r", "SELECT", {"db.system": "postgresql", "error": True})
    pool_timeout["logs"] = [{"fields": [{"key": "exception.type",
                                         "value": "sqlalchemy.exc.TimeoutError"}]}]
    err_root = span(
        "r",
        9,
        logs=[{"fields": [{"key": "exception.type", "value": "OperationalError"}]}],
        tags={"error": True},
    )
    plain_5xx = {"spans": [span("r2", 9, tags={"error": True})]}  # error but no DB evidence
    r = jaeger.analyze([{"spans": [err_root, pool_timeout]}, plain_5xx])
    assert r["db_error_spans"] == 1


def test_fetch_traces_request_shape(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(url=url, params=params)
        return httpx.Response(
            200, json={"data": [trace(1, ("s", 1))]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(jaeger.httpx, "get", fake_get)
    out = jaeger.fetch_traces(100.0, 200.0, url="http://j:1/")
    assert seen["url"] == "http://j:1/api/traces" and len(out) == 1
    assert seen["params"] == {
        "service": "pulseops-api",
        "start": 100_000_000,
        "end": 200_000_000,
        "limit": 200,
    }
