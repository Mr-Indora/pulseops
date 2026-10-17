# S3 — Connection pool exhaustion (load-driven, no infra change)

## Symptoms
- Latency rises and 503 `db_pool_timeout` appears while Postgres itself is reachable.
- Pool checked-out sits at the pool size; checkout wait grows.
- Heavy requests (`/stats/top-products`) hold connections; light routes queue behind them.

## Alert
`DBPoolSaturated` (`db_pool_checked_out / db_pool_size >= 0.9` for 30s).

## Dashboards
"PulseOps - DB & Pool" first (checked-out vs size, checkout wait p95, query duration by operation), then "PulseOps - Service Health" (latency, error ratio, in-progress requests).

## Diagnosis
```promql
max(db_pool_checked_out / db_pool_size)
histogram_quantile(0.95, sum by (le) (rate(db_pool_checkout_wait_seconds_bucket[1m])))
http_requests_in_progress
sum by (route) (rate(http_requests_total[1m]))
```
- `pool_util >= 0.9` and `pool_wait_p95 > 0.1s` → `POOL_EXHAUSTION`.
- Jaeger: the traces' DB time is dominated by the aggregate statement from `/stats/top-products`, and root spans are longer than their DB spans (time spent waiting for a connection).
- Postgres side: `psql "$HOST_DATABASE_URL" -c "select state, count(*) from pg_stat_activity group by 1"`; and `select now()-query_start, query from pg_stat_activity where state='active' order by 1 desc limit 5`.

## Mitigation
Short term: reduce the offending traffic (stop the workload in the exercise; rate-limit or cache the heavy endpoint in real life).
Then pick the actual fix: make the query cheaper, and/or tune `DB_POOL_SIZE` / `DB_POOL_TIMEOUT`. A bigger pool only moves the queue into Postgres, so size it against what the DB can run concurrently.
Do not add retries to this path: retrying a timed-out checkout adds load to an already saturated pool.

## Verification
Pool utilisation below 0.9, checkout wait p95 back near baseline, no `db_pool_timeout` errors, alert resolved; re-run the same profile after the fix and compare.

## Prevention
Alert on utilisation and wait time before timeouts appear; bound statement time (`DB_STATEMENT_TIMEOUT_MS`); isolate or cache heavy aggregates; load-test heavy endpoints with the `pool_pressure` profile before release.
