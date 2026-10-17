# Integration log

Environment: Ubuntu sandbox, 1 vCPU / ~4 GB, **no Docker**. Postgres 16 (apt), Toxiproxy 2.9.0, Prometheus 2.54.1 and Jaeger 1.62.0 (release binaries) ran natively next to the API (uvicorn, 1 worker, DB via Toxiproxy :5433) and Locust. postgres-exporter and Grafana were not run. `docker compose config`, `docker build`, `make up`, S5 and S6 were NOT run.

This is the second integration pass. It was triggered by the target-laptop audit (login 7-10 s, `login failed: 0`, full suite never finishing). The first pass used bcrypt cost 4 and so missed #1.

## Inventory
10 parts merged, no ownership violations, no non-empty `__init__.py`, no stray stubs (unchanged from pass 1). Old pre-fix `reports/` removed, new runs added.

## Static
`compileall` OK. `ruff check .` clean. `promtool check rules`: 5 rules OK. All YAML/JSON parse. Compose only parsed as YAML (no Docker to render it).

## Fixes
| # | Symptom | Root cause | Fix | File |
|---|---|---|---|---|
| 1 | Locust `login failed: 0`, logins 7-10 s, then 401s on `/orders` | (a) `/auth/login` held a pooled DB connection (pool 5, timeout 2 s) for the whole bcrypt: 10 of 20 concurrent logins got 503 `db_pool_timeout`. (b) seeded hashes were cost 12 and `BCRYPT_ROUNDS` reached neither compose nor the Makefile: 20 simultaneous logins = ~20 x 0.3 s CPU on a 1-CPU container (6.4 s worst case here, worse on the laptop; Locust timeout is 10 s) | (a) `db.close()` before bcrypt, regression test. (b) `BCRYPT_ROUNDS=10` in `.env.example`, compose, Makefile; seed now `ON CONFLICT (id) DO UPDATE SET password_hash` so a re-seed re-hashes. Code default stays 12 (Blueprint). Worst case of 20 concurrent logins: 6.4 s -> 1.7 s, all 200 | `app/auth/router.py`, `scripts/seed.py`, `docker-compose.yml`, `.env.example`, `Makefile`, `tests/p4_auth/test_auth.py` |
| 2 | Full `pytest` hangs at the first p3 test | `test_locustfile.py` imports locust, which gevent-monkey-patches the whole pytest process | set `LOCUST_SKIP_MONKEY_PATCH` only around that import (must not leak to the smoke test's Locust subprocess) | `tests/p7_workload/test_locustfile.py` |
| 3 | `test_one_trace_with_child_db_spans` fails only in a full run | the SQLAlchemy instrumentor is a process-wide singleton and p3's `app.main` instrumented its engine first | `SQLAlchemyInstrumentor().uninstrument()` in the p5 client fixture | `tests/p5_obs/conftest.py` |
| 4 | `test_stop_locust_sends_sigint...` flaky | `proc.kill()` without `wait()`; `poll()` could still say running | `proc.wait()` after kill | `cli/run.py` |
| 5 | opaque `login failed: 0`; smoke test could skip silently | audit phases 3-4 | message now `login returned HTTP <status> (<error code>)` or "no response (timeout...)"; `PULSEOPS_REQUIRE_SMOKE=1` turns the skip into a failure; CI e2e job runs the smoke test with it | `workload/locustfile.py`, `tests/p7_workload/test_smoke.py`, `.github/workflows/ci.yml` |
| 6 | Jaeger `/api/traces` timed out on the laptop | `MEMORY_MAX_TRACES=20000` at 512 MiB | 5000 and `mem_limit: 768m` (the audit's measured change; NOT verified here without Docker). The audit also saw 512 MiB still applied after the edit: recreate the container and check `docker inspect -f '{{.HostConfig.Memory}}'` | `docker-compose.yml` |

## Tests (real Postgres 16, `pytest tests --ignore=tests/e2e`)
`139 passed, 0 failed` in ~45 s, including the live smoke test against the running API. `tests/e2e` was not run via pytest. (S2 short run was run directly through the CLI and passed.)

## Open issues (NOT fixed; evidence in docs/RESULTS.md)
1. **S1 FAIL (2 runs)**: diagnosis `POOL_EXHAUSTION`, expected `DB_LATENCY`. Latency saturates the pool, so the higher-priority pool rule matches. `db_time_share` is computed over request time that includes pool wait (0.15 in S1), which also hides the "DB is slow" signal. Needs a rule design decision, not a threshold tweak.
2. **S4 FAIL (2 runs)**: alert never fires, no API-level effect (p95 flat). At 300k orders EXPLAIN was 0.75 ms vs 24 ms (pass 1), too small for p95. Needs a larger table or a read-heavier S4 profile.
3. **Baseline degrades with data size**: 20k orders p95 ~60 ms, 300k orders p95 ~0.8 s on this 1-vCPU box; `HighLatencyP95` and the pool rule are then already true at baseline, so detect times are not meaningful. Re-measure on the target machine.
4. **S6**: `APIDown` has `for: 15s`; a quick restart may never fire it.
5. Every API container start runs `alembic upgrade head` (a restart during S4 re-creates the index).
6. Not verified: compose rendering, Toxiproxy healthcheck, image tags, mem limits, Grafana dashboards, postgres-exporter, GitHub Actions, S5, S6.

## Re-run on your machine
```
cp .env.example .env          # set JWT_SECRET; keep BCRYPT_ROUNDS=10
docker compose config
make up && make migrate && SEED_ORDERS=20000 make seed && make test
make scenario S=S2_db_outage  # then S1, S3..S6; fill docs/RESULTS.md only from reports/
```
