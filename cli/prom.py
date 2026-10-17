"""Tiny Prometheus client. Window helpers evaluate at `end` over the window [start, end]."""
from __future__ import annotations

import math
import os

import httpx

JOB = 'job="pulseops-api"'
SEL = "{" + JOB + "}"


def _secs(start: float, end: float) -> int:
    return max(int(end - start), 10)  # keep >= 2 scrapes inside the 5s-interval window


class Prom:
    def __init__(self, url: str | None = None, client: httpx.Client | None = None) -> None:
        self.url = (url or os.environ.get("PROMETHEUS_URL", "http://localhost:9090")).rstrip("/")
        self.http = client or httpx.Client(timeout=10)

    def _get(self, path: str, **params):
        r = self.http.get(self.url + path, params=params)
        r.raise_for_status()
        body = r.json()
        if body.get("status") != "success":
            raise RuntimeError(f"prometheus error: {body}")
        return body["data"]

    def instant(self, query: str, at: float | None = None) -> float | None:
        params = {"query": query} | ({"time": at} if at else {})
        result = self._get("/api/v1/query", **params)["result"]
        if not result:
            return None
        v = float(result[0]["value"][1])
        return None if math.isnan(v) else v  # NaN = quantile over an empty histogram

    def range(self, query: str, start: float, end: float, step: int = 5) -> list[tuple]:
        data = self._get("/api/v1/query_range", query=query, start=start, end=end, step=step)
        series = data["result"][0]["values"] if data["result"] else []
        return [(float(t), float(v)) for t, v in series]

    def alerts(self) -> list[dict]:
        return self._get("/api/v1/alerts")["alerts"]

    def _quantile(self, metric: str, q: float, start: float, end: float) -> float | None:
        w = _secs(start, end)
        expr = f"histogram_quantile({q}, sum by (le) (increase({metric}_bucket{SEL}[{w}s])))"
        return self.instant(expr, end)

    def window(self, start: float, end: float) -> dict:
        """All numbers the report and the rules need for one time window (None = no data)."""
        w = f"{_secs(start, end)}s"
        total = f"sum(increase(http_requests_total{SEL}[{w}]))"
        errors = f'(sum(increase(http_requests_total{{{JOB},status=~"5.."}}[{w}])) or vector(0))'
        util = self.range(f"db_pool_checked_out{SEL} / db_pool_size{SEL}", start, end)
        changes = self.instant(f"max(changes(process_start_time_seconds{SEL}[{w}]))", end)
        return {
            **{k: self._quantile("http_request_duration_seconds", q, start, end)
               for k, q in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99))},
            "rps": self.instant(f"sum(rate(http_requests_total{SEL}[{w}]))", end),
            "error_ratio": self.instant(f"{errors} / {total}", end),
            "pool_util": max(v for _, v in util) if util else None,
            "pool_wait_p95": self._quantile("db_pool_checkout_wait_seconds", 0.95, start, end),
            "cpu_busy": self.instant(f"avg(rate(process_cpu_seconds_total{SEL}[{w}]))", end),
            "process_restarted": None if changes is None else changes > 0,
        }
