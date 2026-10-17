# S4 — Missing index (slow query after a bad migration state)

## Symptoms
- p95 up on `GET /orders` (and anything filtering by `user_id` ordered by `created_at`); other routes mostly unaffected.
- DB query duration p95 up for `SELECT`; CPU on Postgres rises with load.

## Alert
`SlowDBQueries` (query p95 > 0.3s for 30s) and/or `HighLatencyP95`.

## Dashboards
"PulseOps - DB & Pool" (query duration p95 by operation, rows fetched/returned, transactions/s); "PulseOps - Service Health" (latency by route with INJECT annotation). Jaeger: slowest traces for `GET /orders`.

## Diagnosis
```promql
histogram_quantile(0.95, sum by (le, operation) (rate(db_query_duration_seconds_bucket[1m])))
histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket[1m])))
```
1. Jaeger: the same `db.statement` dominates the DB time of slow traces (`top_statement_share > 0.6`, `db_time_share > 0.6`) → `SLOW_QUERY_MISSING_INDEX`.
2. Take that statement to Postgres and look at the plan:
```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE user_id = 1 ORDER BY created_at DESC LIMIT 20;
\d orders
```
A sequential scan plus sort where an index scan is expected, and no `ix_orders_user_created` in `\d orders`, confirms it.
3. Check migration state: `alembic current` (expect `0002`; `0001` means the index migration is not applied).

## Mitigation
Ship the migration: `alembic upgrade head` (exercise: `recover('S4_missing_index')` does this against `HOST_DATABASE_URL`).
On a large production table build the index without blocking writes (`CREATE INDEX CONCURRENTLY`); the exercise migration is a plain `CREATE INDEX`.

## Verification
`EXPLAIN` now uses `ix_orders_user_created`; query p95 and route p95 back within the PASS bound; alert resolved; `alembic current` = head. Compare the `report.md` before/during/after table.

## Prevention
Migration-state check in deploy (fail if DB is not at head); review query plans for new access patterns; keep the `pg_stat_statements`-style habit of looking at the top statement, which here is the trace-based `top_statement_share` signal.
