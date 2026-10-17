# S6 — API crash and restart

## Symptoms
- Connection refused / 5xx for the duration of the restart, then service returns by itself.
- Metrics gap for the API target, counters reset, `process_start_time_seconds` changes.
- In-flight requests at the moment of the crash fail.

## Alert
`APIDown` (`up{job="pulseops-api"} == 0` for 15s) and/or `HighErrorRate`. A fast restart may recover before `for` elapses, so the alert may not fire; the restart is still visible in metrics.

## Dashboards
"PulseOps - Service Health" (request rate drop, error spike, annotations); Prometheus: `up{job="pulseops-api"}`.

## Diagnosis
```promql
up{job="pulseops-api"}
changes(process_start_time_seconds{job="pulseops-api"}[5m]) > 0
```
- `process_restarted` → `APP_RESTART` (rule ordering puts it first).
- Container facts: `docker inspect -f '{{.State.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}} exit={{.State.ExitCode}}' pulseops-api`; `docker logs --tail 100 pulseops-api` for the crash reason.
- Note the container start runs `alembic upgrade head` before Uvicorn, so startup time includes migrations.

## Mitigation
Compose `restart: unless-stopped` brings the container back; the exercise's `recover()` waits (bounded) for `/health/live` to return 200. If it does not return, read the logs; a crash loop needs the root cause fixed, not more restarts.

## Verification
`/health/live` and `/health/ready` return 200, `up == 1`, request rate and error ratio back to baseline, `RestartCount` explained.

## Prevention
Find and fix the crash cause; graceful shutdown (`stop_grace_period`, Uvicorn graceful timeout) for planned restarts; in real deployments run several instances with rolling restarts so one crash is not a full outage.
