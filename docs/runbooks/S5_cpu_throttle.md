# S5 — CPU throttle (API container starved of CPU)

## Symptoms
- p95 up across all routes, including ones with little DB work.
- DB query durations and Postgres load look normal; the time is spent in the app, not in SQL.
- Process CPU pinned at its quota.

## Alert
`HighLatencyP95`.

## Dashboards
"PulseOps - Service Health" (latency, in-progress requests, process CPU); "PulseOps - DB & Pool" to confirm the DB side is healthy. Jaeger: root spans long while DB child spans stay short.

## Diagnosis
```promql
rate(process_cpu_seconds_total[1m])
http_requests_in_progress
histogram_quantile(0.95, sum by (le, operation) (rate(db_query_duration_seconds_bucket[1m])))
```
- `p95_ratio > 2`, `db_time_share < 0.4`, CPU near the container limit → `CPU_SATURATION`.
- Confirm the quota: `docker inspect -f '{{.HostConfig.NanoCpus}}' pulseops-api` and `docker stats --no-stream pulseops-api`.
- Distinguish from S1: there DB spans are slow; here they are not.

## Mitigation
Exercise: `docker update --cpus 1.0 pulseops-api` (or `recover('S5_cpu_throttle')`).
Real life: raise the CPU limit, add instances, or remove CPU-heavy work (for example bcrypt cost on a hot path).

## Verification
CPU rate below the limit, p95 back within the PASS bound, quota reads as the configured `1.0`, alert resolved.

## Prevention
Alert on CPU saturation (process CPU vs limit) in addition to latency; load-test with the production CPU limit; avoid CPU-heavy work in request paths.
