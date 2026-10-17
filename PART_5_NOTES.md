# PART 5 — App Observability

## What was built
`app/obs/{logging,metrics,tracing,middleware,setup}.py` (230 lines) and `tests/p5_obs/` (11 tests).
`setup_observability(app, engine)` is idempotent per app and wires, in this order: JSON logging, pool
gauges and DB timing hooks, the ASGI middleware, `GET /metrics`, then OTel (last, so the OTel middleware
wraps ours and the request log line is written inside the request span, which is what gives it `trace_id`).

## Design notes
- **Pool gauges**: `Gauge.set_function` on `engine.pool.size()` / `.checkedout()`. Evaluated at scrape time, no thread.
- **`db_pool_checkout_wait_seconds`**: `engine.pool.connect` is wrapped on the instance with a perf_counter timer
  (observed in `finally`). It therefore covers queue wait, `pool_pre_ping` and a fresh connect, and it records the
  wait of checkouts that fail with `pool_timeout`, which is the exhaustion case. SQLAlchemy's `checkout` event
  fires only after the connection is obtained, so it cannot measure the wait. Pool wrap is guarded against double wrapping.
- **`db_query_duration_seconds`**: `before_cursor_execute` / `after_cursor_execute`, plus `handle_error` so failed
  statements (e.g. `statement_timeout`) are observed too. `operation` = first SQL keyword, upper-cased.
- **Route label**: read from `scope["route"]` after the call (FastAPI stores the matched route there); no match -> `unmatched`.
- **Exceptions**: counted as 500, logged at `error` with `error_type`, then re-raised.
- **`/metrics`** is `async def` so a saturated sync-handler threadpool (S3) cannot starve scrapes. It is excluded
  from metrics, logs and tracing.
- **Logs**: uvicorn/stdlib records go through the same JSON pipeline. `uvicorn.access` is silenced because the
  middleware writes the one canonical `event="request"` line.
- **Tracing**: `BatchSpanProcessor` + OTLP/HTTP (2s timeout). Export runs in a background thread with a bounded
  queue, so a dead collector produces warning logs and dropped spans, never a failed request.
  Provider is created lazily via `get_provider()` (tests use it to attach an in-memory exporter).

## Verified (real runs in this sandbox)
- `pytest tests/p5_obs`: **11 passed**. Covers: all Contract 4.7 metric families on `/metrics`; route label is the
  template and 404s are `unmatched`; `/metrics` not self-counted; bucket list equals Contract; query-duration and
  checkout-wait counters increment after a DB call; pool gauges read live (`checked_out` 1 while a connection is held);
  500 counted and logged; exactly one request log line with `trace_id` that matches a finished span and
  `X-Request-ID` equal to the logged `request_id`; one trace with a root span (`service.name=pulseops-api`) and
  child DB spans with `db.statement`/`db.system` and no parameter values; app serves with the OTLP endpoint
  pointed at a closed port; setup called twice does not double count.
- Ran under real `uvicorn` with `curl`: `/metrics` shows the contract metrics, one JSON line per request, uvicorn
  startup lines are JSON, no duplicate access log.

## NOT verified
- **PostgreSQL / psycopg**: no Postgres in the sandbox. Tests use file-backed SQLite (real `QueuePool`). `db.system`
  was only asserted non-empty; it will be `postgresql` with the psycopg dialect but I did not observe that.
- **Jaeger / real OTLP collector**: not available. Trace shape was checked with an in-memory exporter only.
- **Docker, Prometheus scrape, Grafana**: not run.
- Behaviour under real pool exhaustion (S3) was not exercised, only the code path by reasoning.

## Dependency requests (for Part 1)
1. **Pin `sqlalchemy>=2,<2.1`.** `opentelemetry-instrumentation-sqlalchemy` 0.66b1 refuses to instrument
   SQLAlchemy 2.1.x ("nothing can be instrumented"). With `>=2` alone pip installs 2.1.4 and there are **no DB spans**
   (I hit this; tests pass on 2.0.54).
2. Tests use `fastapi.testclient.TestClient`, which needs `httpx` (already a runtime dep). No other additions.

## Contract concerns
- Contract 4.7 gives buckets only for the HTTP histogram; the same bucket list is reused for the two DB histograms.
- When an unhandled exception reaches Starlette's outermost error handler (P3's generic `Exception` handler), that
  500 response is sent outside this middleware, so it does **not** carry `X-Request-ID`. It is still counted and logged,
  and `request.state.request_id` is set for the error body.
- `SQLAlchemyInstrumentor` is a process-wide singleton: it instruments one engine per process (the app has one).
- `db.statement` is the attribute name emitted by this instrumentation version by default; P9's Jaeger parser relies on it.
- `process_*` metrics come from the default prometheus_client registry (Linux only).
