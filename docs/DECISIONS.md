# Decisions (short ADRs)

Format: decision, why, alternatives, trade-off, what changes in production.
All limits mentioned here are the Contract's; nothing below is a measurement.

## ADR-1 No service/repository layers
- **Decision:** route → SQLAlchemy → DB. Handlers use the session directly.
- **Why:** the app has four tables and a handful of routes; extra layers add files without adding behaviour, and the project is about reliability signals, not domain design.
- **Alternatives:** service layer; repository pattern; CQRS-style split.
- **Trade-off:** SQL lives in handlers, so reuse is by copy and handlers are harder to unit-test without a DB (tests use a real Postgres instead).
- **Production:** add a layer once two entry points (API, workers, jobs) share the same business rules or the same query appears in several places.

## ADR-2 Sync SQLAlchemy + psycopg 3
- **Decision:** synchronous engine, FastAPI runs handlers in a threadpool.
- **Why:** a bounded pool (`DB_POOL_SIZE`, `DB_POOL_TIMEOUT`, `max_overflow=0`) turns pool exhaustion into a real, reproducible failure (S3) instead of something hidden by async concurrency.
- **Alternatives:** async SQLAlchemy + asyncpg; larger pool; PgBouncer.
- **Trade-off:** concurrency is limited by threads and pool size; async would scale differently and fail differently.
- **Production:** choose by workload measurements; consider PgBouncer and an async stack once connection count, not code simplicity, is the constraint.

## ADR-3 Toxiproxy for network faults
- **Decision:** the API reaches Postgres only through Toxiproxy `:5433`; latency and outage are toxics / proxy toggles.
- **Why:** real network faults with zero app code; faults are removable by API call, so `recover()` is idempotent.
- **Alternatives:** `tc netem` in the container; stopping the Postgres container; a fault-injecting library in the app; chaos tooling on Kubernetes.
- **Trade-off:** proxy adds one hop for every query, and it simulates the network path only, not Postgres internals (disk, locks).
- **Production:** inject at the real boundary (service mesh, `netem`, cloud fault-injection service) and never put a test proxy in the production data path.

## ADR-4 Deterministic diagnosis (rules, not ML)
- **Decision:** a small ordered rule table over evidence (`cli/rules.py`); output is a ranked list with evidence and a plain-English reason; `UNKNOWN` if nothing matches.
- **Why:** explainable, unit-testable with synthetic evidence, no training data needed, never claims more than the evidence shows.
- **Alternatives:** ML/anomaly detection; LLM-based RCA; manual runbook only.
- **Trade-off:** only recognises the six known shapes; thresholds are hand-set and tuned on one machine; overlapping failures can mis-rank.
- **Production:** keep rules as the explainable core, add service-specific signals, and revisit thresholds against real incident history before adding anything probabilistic.

## ADR-5 No Alertmanager
- **Decision:** Prometheus alert rules only; the CLI polls `/api/v1/alerts`.
- **Why:** one fewer service on a memory-constrained laptop; the experiment only needs to know that an alert fired and when.
- **Alternatives:** Alertmanager with a webhook receiver; Grafana alerting.
- **Trade-off:** no grouping, deduplication, silencing, routing or notification delivery, so "alert fired" is not "someone was paged".
- **Production:** add Alertmanager (or equivalent) with routing, inhibition and an on-call receiver; alert on symptoms and keep cause-level alerts as lower severity.

## ADR-6 Single Uvicorn worker
- **Decision:** `--workers 1`.
- **Why:** `prometheus-client` metrics and pool gauges aggregate trivially in one process; avoids multi-process mode and a second source of variance in experiments.
- **Alternatives:** several workers with Prometheus multiprocess mode; several containers behind a load balancer.
- **Trade-off:** one process, one pool, one CPU quota (`cpus: "1.0"`); not representative of a multi-instance deployment, and S6 means a full outage rather than a degraded one.
- **Production:** run multiple instances, scrape each, and aggregate in PromQL; make restarts rolling.

## ADR-7 100% trace sampling
- **Decision:** sample every request.
- **Why:** the diagnosis rules read sampled traces from a window; at demo scale, complete traces give simpler, more reliable evidence.
- **Alternatives:** head-based probabilistic sampling; tail-based sampling that keeps errors and slow traces.
- **Trade-off:** per-request export cost and storage grow with traffic; Jaeger all-in-one is not durable storage.
- **Production:** sample (tail-based if errors and slow requests must be kept), set retention, and use durable trace storage.

## ADR-8 Demo-scale scrape and evaluation intervals (5s) and short `for` durations
- **Decision:** scrape every 5s, evaluate rules every 5s, alerts use `for: 15s` / `30s`, rate windows are 1m.
- **Why:** an experiment run must detect and recover within minutes, so signals have to arrive quickly.
- **Alternatives:** longer intervals with longer windows.
- **Trade-off:** more samples and more sensitive alerts, so more false-positive risk on a noisy service; short `for` is easy to trip with brief spikes.
- **Production:** longer intervals, windows and `for` chosen from the service's SLOs; consider multi-window burn-rate alerts instead of fixed thresholds.

## ADR-9 bcrypt cost 10 for the load stack (code default stays 12)
- **Decision:** `.env.example`, compose and the Makefile set `BCRYPT_ROUNDS=10`; the code default stays 12 (Blueprint Part 4). `make seed` re-hashes the seeded users, so changing the value and re-seeding takes effect.
- **Why:** with cost 12, 20 Locust users logging in at once cost about 20 x 0.3 s of CPU on a 1-CPU API container. On the target laptop that gave 7-10 s logins and `login failed: 0` (client timeout). Measured in the integration sandbox: 20 concurrent logins took up to 6.4 s at cost 12 and 1.7 s at cost 10.
- **Also fixed:** `/auth/login` no longer holds a pooled DB connection while bcrypt runs (the pool is 5; before the fix 10 of 20 concurrent logins got `503 db_pool_timeout`).
- **Trade-off:** each +1 of cost doubles the work of an offline guess against a stolen hash; 10 is still within common guidance for bcrypt, but it is a load-test trade-off.
- **Production:** use cost 12 or more, or move to a slower KDF, and run hashing off the request path or on a separate worker pool.
