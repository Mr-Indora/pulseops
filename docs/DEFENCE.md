# Defence map

For each part: likely interviewer questions and **where the evidence is**. Open the file, read it, and answer
from what it actually does. No scripted answers here on purpose. If a file does not support a claim, do not make it.

## Part 1 — Foundation (`Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml`)

| Question | Look at |
|----------|---------|
| Why does the API connect through Toxiproxy, and which paths bypass it? | `docker-compose.yml` env vars; `.env.example`; ARCHITECTURE "Data flow" |
| What happens on container start, and what does that mean for S6 recovery time? | `Dockerfile` CMD |
| How are the stack's resources bounded, and what is the API's CPU quota? | `docker-compose.yml` (`mem_limit`, `cpus`) |
| Why are image tags pinned? | `docker-compose.yml` image lines |
| How do you reproduce the whole thing from a clean machine? | `Makefile`, README quickstart |

## Part 2 — Database (`app/db`, `migrations`, `scripts/seed.py`)

| Question | Look at |
|----------|---------|
| Which constraints does the schema enforce, and who enforces them (DB or app)? | `app/db/models.py`, `migrations/versions/0001_initial.py` |
| What exactly does migration 0002 do and why is its downgrade the S4 injection? | `migrations/versions/0002_orders_user_created_idx.py` |
| How does the seed stay fast and idempotent? Why `ANALYZE` after? | `scripts/seed.py` |
| What do the query plans look like with and without the index? | `PART_2_NOTES.md` (EXPLAIN output), `tests/p2_db/` |
| Why do migrations and seed bypass the proxy? | `migrations/env.py`, ARCHITECTURE "Data flow" |

## Part 3 — API core (`app/main.py`, `app/api`, `app/core`, `app/schemas.py`)

| Question | Look at |
|----------|---------|
| Why can stock never be oversold, and how is deadlock avoided? | `app/api/orders.py`; concurrency test in `tests/p3_api/` |
| What does a repeated `Idempotency-Key` return and what enforces it? | `app/api/orders.py`, unique constraint in `models.py` |
| Why is keyset pagination used for `GET /orders`? | `app/api/orders.py`; index in migration 0002 |
| Which handlers are retried and which never are? | `app/api/*.py` use of `retry_transient` |
| How do DB failures become 503 with a stable error body? | `app/core/errors.py`, `app/reliability/policy.py` (`map_db_error`) |

## Part 4 — Auth (`app/auth`)

| Question | Look at |
|----------|---------|
| How are passwords stored, and what is the bcrypt cost knob for? | `app/auth/security.py` |
| How does login avoid revealing whether a user exists (response and timing)? | `app/auth/router.py` |
| What pins the JWT algorithm, and what happens on expired or tampered tokens? | `app/auth/security.py`, `app/auth/deps.py`, `tests/p4_auth/` |
| What happens if `JWT_SECRET` is missing? | `app/auth/security.py` |
| What is deliberately out of scope (refresh tokens, rate limiting, etc.)? | `PART_4_NOTES.md` security checklist |

## Part 5 — App observability (`app/obs`)

| Question | Look at |
|----------|---------|
| Why is `route` a template, and what is used for unmatched paths? | `app/obs/middleware.py`; metrics test in `tests/p5_obs/` |
| How are pool gauges read, and why at scrape time? | `app/obs/metrics.py` |
| How is checkout wait time measured? | `app/obs/metrics.py`, `PART_5_NOTES.md` |
| How does a log line link to a trace? | `app/obs/logging.py`; `trace_id` in the request log |
| What happens if the OTLP collector is down? | `app/obs/tracing.py`; test in `tests/p5_obs/` |

## Part 6 — Observability stack (`deploy/observability`)

| Question | Look at |
|----------|---------|
| Walk through one alert expression and say what it measures. | `prometheus/alerts.yml` |
| Why these thresholds and `for` durations, and what would you change in production? | `alerts.yml`, DECISIONS ADR-8 |
| How are dashboards and datasources provisioned (no clicking)? | `grafana/provisioning/`, `grafana/dashboards/*.json` |
| How do CLI annotations show up on panels? | dashboard JSON annotation settings; `cli/grafana.py` |
| How was the config validated? | `PART_6_NOTES.md`, `tests/e2e/test_stack.py::test_alert_rules_loaded` |

## Part 7 — Workload (`workload/`)

| Question | Look at |
|----------|---------|
| What load mix does each profile generate, and where are the numbers defined? | `workload/profiles.py` |
| Why is 409 counted as success but 5xx as failure? | `workload/locustfile.py` |
| Why are request names grouped by route template? | `workload/locustfile.py` (`name=`), compare Prometheus `route` label |
| What makes `pool_pressure` exhaust the pool? | `profiles.py` + `/stats/top-products` in `app/api/stats.py` |
| How is the load run headless with CSV output? | `Makefile` `load-*` targets, `cli/run.py` |

## Part 8 — Reliability and faults (`app/reliability`, `faults/`)

| Question | Look at |
|----------|---------|
| Why this pool size and timeout, and what does exhaustion look like? | `app/reliability/policy.py` (`ENGINE_OPTIONS`), `.env.example` |
| When do retries help, and how can they make an outage worse? | `retry_transient` in `policy.py`, DECISIONS, S3/S2 runbooks |
| How does each scenario inject and recover, and why is it idempotent? | `faults/injector.py`, `faults/scenarios.yaml` |
| Why must S2 recover without an API restart? | `pool_pre_ping` in `policy.py`; `docs/runbooks/S2_db_outage.md` |
| How do you prove the system is back to a clean state after recover()? | `tests/p8_faults/`, `PART_8_NOTES.md` |

## Part 9 — CLI (`cli/`)

| Question | Look at |
|----------|---------|
| Explain each diagnosis rule and its ordering. | `cli/rules.py`, blueprint Section 6 |
| How does it tell DB latency from a missing index? | `rules.py` (`top_statement_share`), `cli/jaeger.py` |
| What is PASS, precisely, and is diagnosis part of it? | `cli/run.py`, a `report.md` |
| What if the run crashes or is interrupted mid-injection? | `cli/run.py` `finally` + recover; `tests/p9_cli/` |
| What does a report say when data is missing? | `cli/report.py` (`n/a`), caveats section |

## Part 10 — Quality and docs (`tests/e2e`, `ci.yml`, `docs/`)

| Question | Look at |
|----------|---------|
| What does CI check, and what does it deliberately not run? | `.github/workflows/ci.yml` |
| What do the e2e tests prove that unit tests cannot? | `tests/e2e/test_stack.py` |
| How do you keep numbers honest? | `docs/RESULTS.md` header, `docs/CV_BULLETS.md` rules |
| What are the known limits and what changes in production? | README "does NOT claim", `docs/DECISIONS.md` |
| How would you debug each failure on call? | `docs/runbooks/S1..S6` |
