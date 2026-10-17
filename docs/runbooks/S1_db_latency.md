# S1 — DB latency (network path to Postgres is slow)

## Symptoms
- p95 latency up on every route that touches the DB; error rate roughly unchanged.
- Throughput drops if load is closed-loop (clients wait longer).
- Pool checked-out rises because connections are held longer.

## Alert
`HighLatencyP95` (p95 > 0.5s for 30s). `SlowDBQueries` may also fire.

## Dashboards
Grafana: "PulseOps - Service Health" (latency p95, annotations), "PulseOps - DB & Pool" (query duration p95 by operation, pool).
Jaeger: service `pulseops-api`, sort by duration.

## Diagnosis
Key question: is the slowdown spread across all statements, or concentrated in one?
```promql
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[1m])))
histogram_quantile(0.95, sum by (le, operation) (rate(db_query_duration_seconds_bucket[1m])))
db_pool_checked_out / db_pool_size
```
- In Jaeger, open several traces of different routes: DB child spans are all slow by a similar amount → spread → `DB_LATENCY` (rule: high `db_time_share`, `top_statement_share <= 0.6`).
- One statement dominating instead → see S4.
- Rule out the DB itself: `docker compose exec postgres pg_isready`; compare with a direct query on host `:5432` (bypasses the proxy): `psql "$HOST_DATABASE_URL" -c 'select 1'` (timing with `\timing`).
- Check the proxy: `curl $TOXIPROXY_URL/proxies/postgres/toxics` (a latency toxic here is the injected cause in this exercise).

## Mitigation
Exercise: `python -c "from faults.injector import recover; recover('S1_db_latency')"`.
Real life: fix or route around the slow network hop; shed non-critical load meanwhile; do not raise timeouts blindly (it hides the problem and holds pool connections longer).

## Verification
p95 back within the PASS bound of baseline, `HighLatencyP95` resolves, `/health/ready` 200, no leftover toxics (`toxics` list empty).

## Prevention
Alert on DB query latency separately from HTTP latency (already: `SlowDBQueries`); keep statement timeout and pool timeout bounded (`DB_STATEMENT_TIMEOUT_MS`, `DB_POOL_TIMEOUT`); keep retries limited to idempotent reads so latency does not turn into a retry storm.
