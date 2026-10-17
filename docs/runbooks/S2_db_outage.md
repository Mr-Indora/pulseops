# S2 — DB outage (connections refused / reset)

## Symptoms
- 5xx on DB-backed routes with error codes `db_unavailable` or `db_pool_timeout`.
- `GET /health/ready` returns 503 `{"status":"degraded","reason":"db"}`; `/health/live` still 200.
- `/products`, `/orders`, `/stats/*` fail; `/metrics` and `/health/live` keep working.

## Alert
`HighErrorRate` (5xx ratio > 5% for 30s).

## Dashboards
"PulseOps - Service Health" (error ratio, request rate by route); "PulseOps - DB & Pool" (pool, postgres-exporter connections).
Jaeger: error traces with `OperationalError` on DB spans.

## Diagnosis
```promql
sum(rate(http_requests_total{status=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))
sum by (route, status) (rate(http_requests_total[1m]))
```
- `curl -s localhost:8000/health/ready` and inspect the error body code.
- Is it the proxy or Postgres? `curl $TOXIPROXY_URL/proxies/postgres` (`"enabled"`), then `docker compose ps postgres` and `docker compose exec postgres pg_isready`, then a direct connect on `:5432`.
- Jaeger: spans with connection errors → `db_error_spans > 0` and `error_ratio > 0.2` → `DB_DOWN`.
- Rule out an app crash: `docker inspect -f '{{.State.Status}} {{.RestartCount}}' pulseops-api` (restart → S6).

## Mitigation
Exercise: `python -c "from faults.injector import recover; recover('S2_db_outage')"` (re-enables the proxy).
Real life: restore the database or the path to it. The API must recover on its own without a restart: `pool_pre_ping=True` discards dead connections on checkout.

## Verification
`/health/ready` 200 **without restarting `pulseops-api`** (`StartedAt` unchanged: `docker inspect -f '{{.State.StartedAt}}' pulseops-api`); error ratio back below the PASS bound; alert resolved.

## Prevention
Keep `connect_timeout` and pool timeout short so requests fail fast instead of piling up; map DB errors to 503 with a stable code; readiness probe on the DB so a load balancer can stop routing; never auto-retry writes. Real deployments need DB replication/failover, which this project does not have.
