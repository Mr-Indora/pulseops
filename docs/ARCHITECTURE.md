# Architecture

Source of truth: the Shared Contract (blueprint Section 4). If this file and the Contract disagree, the Contract wins.

## Components and ports

| Component | Port | Notes |
|-----------|------|-------|
| `pulseops-api` (FastAPI, Uvicorn, 1 worker) | 8000 | `cpus: "1.0"`, `restart: unless-stopped`, `stop_grace_period: 30s` |
| PostgreSQL 16 | 5432 | published to host; internal `postgres:5432` |
| Toxiproxy | 5433 (proxy), 8474 (control API) | proxy `postgres`: `0.0.0.0:5433` → `postgres:5432` |
| postgres-exporter | 9187 | connects directly to Postgres, not via the proxy |
| Prometheus | 9090 | scrape and rule evaluation every 5s |
| Grafana | 3000 | anonymous viewer enabled for the demo; datasource uids `prometheus`, `jaeger` |
| Jaeger all-in-one | 16686 (UI), 4318 (OTLP HTTP) | |

Domain: `users`, `products`, `orders`, `order_items` (schema in Contract 4.4). Routes: Contract 4.5.

## Data flow

1. Client (Locust, curl, e2e tests) calls the API on `:8000`.
2. Middleware assigns `request_id`, increments in-progress, starts the timer.
3. Auth dependency verifies the JWT (protected routes).
4. Route handler uses SQLAlchemy directly (no service/repository layer) over `DATABASE_URL`, which points at **Toxiproxy `:5433`**, not Postgres.
5. Toxiproxy forwards to `postgres:5432`. Fault injection edits the proxy, so the app code never changes.
6. Middleware records metrics, writes one JSON log line, and the request ends as one trace.

Direct paths that bypass the proxy on purpose, so injected faults do not break them:
migrations (`MIGRATION_DATABASE_URL`), seed / CLI / faults (`HOST_DATABASE_URL`), postgres-exporter.

## Signal flow

| Signal | Producer | Transport | Consumer |
|--------|----------|-----------|----------|
| Metrics | `app/obs/metrics.py`, `GET /metrics` | Prometheus scrape (5s) | Prometheus, Grafana, CLI (`/api/v1/query*`, `/api/v1/alerts`) |
| Traces | OTel FastAPI + SQLAlchemy instrumentation | OTLP HTTP → `jaeger:4318` | Jaeger UI, Grafana, CLI (`/api/traces`) |
| Logs | structlog JSON on stdout | container logs | `docker compose logs`; `trace_id` links a line to a trace |
| Annotations | CLI | Grafana `/api/annotations`, tag `pulseops` | Grafana panels |

Trace contract: `service.name = pulseops-api`, root span per request, one child span per SQL statement with
`db.statement` (parameterised text) and `db.system=postgresql`.

### Metrics (names and labels fixed)

`http_requests_total{method,route,status}`, `http_request_duration_seconds{method,route}`,
`http_requests_in_progress`, `db_pool_size`, `db_pool_checked_out`, `db_pool_checkout_wait_seconds`,
`db_query_duration_seconds{operation}`, plus default `process_*`. `route` is always the route template.

### Alerts (`deploy/observability/prometheus/alerts.yml`)

`HighLatencyP95`, `HighErrorRate`, `DBPoolSaturated`, `SlowDBQueries`, `APIDown` — thresholds and `for`
durations in Contract 4.10. There is no Alertmanager; the CLI polls `/api/v1/alerts`.

## Experiment flow (`python -m cli run <scenario>`)

One continuous Locust run with phases: BASELINE → inject (+ Grafana annotation `INJECT`) → DETECT (poll for the
expected alert) → DIAGNOSE (PromQL + Jaeger evidence → rules) → recover (+ annotation `FIX`) → VERIFY →
stop Locust and write `reports/<run_id>/`. Phase lengths are flags (`--baseline`, `--verify`).
PASS needs all three: `p95 <= 1.2 x baseline`, `error% < 1%`, diagnosis equals expected (reported separately).

## Scenarios

| ID | Injection | Fix | Expected alert | Expected diagnosis |
|----|-----------|-----|----------------|--------------------|
| S1_db_latency | Toxiproxy latency toxic on the DB path | remove toxic | `HighLatencyP95` | `DB_LATENCY` |
| S2_db_outage | Toxiproxy proxy disabled | proxy enabled, no API restart | `HighErrorRate` | `DB_DOWN` |
| S3_pool_exhaustion | `pool_pressure` workload only | stop load / tune / optimise query | `DBPoolSaturated` | `POOL_EXHAUSTION` |
| S4_missing_index | `alembic downgrade -1` | `alembic upgrade head` | `SlowDBQueries` / `HighLatencyP95` | `SLOW_QUERY_MISSING_INDEX` |
| S5_cpu_throttle | `docker update --cpus 0.2 pulseops-api` | `--cpus 1.0` | `HighLatencyP95` | `CPU_SATURATION` |
| S6_crash_restart | `docker kill pulseops-api` | compose restart policy | `APIDown` / `HighErrorRate` | `APP_RESTART` |

Runbooks: [docs/runbooks/](runbooks/).
