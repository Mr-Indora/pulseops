# CV bullets

## Status after integration (2026-10-17)

Measured so far (1-vCPU sandbox, not representative, N=1 per row): S2 and S3 PASS (run_ids in RESULTS.md); S1 and S4 FAIL; S5 and S6 NOT RUN. The S4 bullet and its placeholders must NOT be filled. The scenario-count placeholders may only be filled after a run on your own machine; until then do not put a pass count on a CV.

## Rules (non-negotiable)

1. **No number on the CV without a matching report in `reports/`.** Every `{PLACEHOLDER}` below is filled only from a row of `docs/RESULTS.md`, and that row must name a `run_id` whose `reports/<run_id>/report.md` exists.
2. A scenario that failed or was not run does not get a bullet. List it in the README under known limitations instead.
3. Do not write "production-ready", "scalable" or similar. Write "laptop-scale, reproducible fault-injection experiments".
4. List only skills you used hands-on in this repo (FastAPI, PostgreSQL, SQLAlchemy, Alembic, Docker Compose, Prometheus, Grafana, OpenTelemetry, Jaeger, Toxiproxy, Locust, GitHub Actions, as applicable).
5. State AI assistance honestly ("AI-assisted; designed and verified by me") and only if you can explain and debug the code.
6. If a placeholder cannot be filled from RESULTS.md, delete the clause that contains it; never estimate.
7. Keep the "N=1 / single run" qualifier in the bullet if RESULTS.md shows one run.

## Placeholder source map

| Placeholder | RESULTS.md table → column |
|-------------|---------------------------|
| `{S4_P95_BASE}`, `{S4_P95_DURING}`, `{S4_P95_AFTER}` | Latency and errors by phase → p95 base / during / after (S4 row) |
| `{S4_TTD}` | Per-scenario outcome → time_to_detect (S4 row) |
| `{S4_RUN_ID}` | Per-scenario outcome → run_id (S4 row) |
| `{SCENARIOS_PASSED}` | Count of rows with PASS in Per-scenario outcome |
| `{SCENARIOS_RUN}` | Count of scenarios with a run_id |
| `{SX_*}` | Same pattern for any other scenario `SX` |

## Templates

- Built a FastAPI + PostgreSQL orders service instrumented with Prometheus metrics, OpenTelemetry traces and structured logs, run locally with Docker Compose.
- Designed 6 reproducible fault-injection scenarios (Toxiproxy network faults, container CPU throttling, migration rollback) and automated baseline → inject → detect → diagnose → recover → verify runs that generate reports; `{SCENARIOS_PASSED}` of `{SCENARIOS_RUN}` scenarios passed in my runs (N={N}, laptop-scale).
- In the missing-index scenario, traced a p95 change of `{S4_P95_BASE}` → `{S4_P95_DURING}` → `{S4_P95_AFTER}` to a single slow SQL statement and restored latency by applying an Alembic migration; the alert fired `{S4_TTD}` after injection (single run, run `{S4_RUN_ID}`).
- Wrote a deterministic, rule-based diagnosis engine over Prometheus and Jaeger evidence (returns `UNKNOWN` when no rule matches), unit-tested with table-driven cases.
- Set up CI (ruff, pytest against a Postgres service container, pip-audit, Docker build) and Prometheus alert rules plus provisioned Grafana dashboards for the service.

## Checklist before sending a CV

- [ ] Every number traces to a `run_id` in RESULTS.md and a report under `reports/`.
- [ ] No bullet for a scenario that failed or was not run.
- [ ] No banned wording (rule 3).
- [ ] I can open the code and explain each bullet (see `docs/DEFENCE.md`).
