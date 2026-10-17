# PART 9 - CLI notes

## What was built
`cli/{__main__,prom,jaeger,grafana,rules,run,report}.py` and `tests/p9_cli/**`.
Commands: `python -m cli list | run <scenario> [--baseline 60 --verify 60 --detect 120 --diagnose 30]
| diagnose --window <s> | verify [--window <s>] | report [<run_id>|latest]`.
Exit codes: `run` 0 = PASS, 1 = FAIL, 2 = error (unreachable service, unknown scenario).

## How it was verified (real outcomes)
- `pytest tests/p9_cli`: **45 passed** (rules table incl. ambiguous/UNKNOWN/boundary cases, priority order,
  report rendering with fixture + "n/a" handling, phase-window maths, finally-recover for exception /
  Ctrl-C / failing recover, Jaeger maths, mocked Prometheus/Grafana request shapes, real-subprocess
  SIGINT stop). `ruff check` (E,F,W,I,B, line length 100) clean.
- `python -m cli list` works offline (needs only `faults/scenarios.yaml` via Part 8's injector).
- `prom.py` was run against a **real Prometheus 2.54.1** scraping a *synthetic exporter* that exposes the
  Contract 4.7 metric names (not the real API). PromQL parsed/evaluated; p95, rps, error ratio, pool util,
  pool wait, restart detection (`changes(process_start_time_seconds)`) returned the values the synthetic
  data implies. `diagnose` and `verify` commands ran against it; Jaeger being unreachable degraded to
  `None` evidence -> `UNKNOWN`, no crash.

## NOT verified (be explicit)
- **No live PulseOps stack was available**, so the acceptance item "short run
  (`--baseline 20 --verify 20`) against a live stack" is **NOT verified**. `run()` is covered only with mocks.
- Never run against the real Jaeger: the `/api/traces` field handling (`references`, `tags`, `logs`,
  `db.statement`, `error`) follows Jaeger's documented JSON but is untested on real OTel spans.
  Riskiest part: `db_error_spans` (DB_DOWN needs `> 0`). If connection failures do not mark a span with
  `db.system` or log an OperationalError/psycopg exception, S2 would diagnose as UNKNOWN. Check this first.
- Locust integration (`workload/locustfile.py`, Part 7), Toxiproxy/Docker faults (Part 8): not exercised.
- Grafana annotations: request shape unit-tested only.

## Decisions / deviations (please review)
1. **Baseline is always the `normal` profile.** If the scenario's `workload_profile` is not `normal`
   (S3 `pool_pressure`), it is started as an *additional* Locust process at inject time and stopped right
   before `recover()`. Otherwise S3's baseline would already be saturated. Spec said one Locust run with the
   scenario's profile; this keeps the baseline meaningful.
2. Locust is started with `-u/-r` from `workload.profiles.PROFILES[name]["users"|"spawn_rate"]` when
   importable (Contract's CLI line has no `-u`, and headless Locust defaults to 1 user). If Part 7 sets users itself this is harmless.
3. `top_statement_share` = share of total DB time owned by the statement with the **highest mean duration**
   (Section 6 says "slowest single statement"; ranking by total time made a uniform +200ms slowdown risk
   looking like one hot statement, because the most frequent query owns ~50% of time).
4. `cpu_busy` "near limit" is undefined in Section 6. Rule: `cpu_busy >= 0.8 * cpu_limit`, where cpu_limit
   comes from `docker inspect pulseops-api` (NanoCpus), falling back to 1.0 (compose `cpus`). Thresholds in
   `cli/rules.py:THRESHOLDS`.
5. `Rule` is a 4-field NamedTuple `(id, keys, test, why)`; `keys` = evidence attached to a match.
6. `expected_alert` may be a string like `"SlowDBQueries / HighLatencyP95"` (Section 5.1) or a list; both parsed.
7. `diagnose` (standalone) compares the last N seconds with the N seconds before; may be contaminated (stated in the report caveats).
8. `verify` is not defined precisely in the spec: it checks the last window against the newest report's
   baseline p95 (n/a if none), error < 1%, and no alerts firing. Needs live traffic.
9. PASS booleans use Prometheus (server-side) data; a missing value is `None`/"n/a" and can never yield PASS.
10. Locust writes its CSVs straight into `reports/<run_id>/` (`--csv reports/<run_id>/locust` ->
    `locust_stats.csv`), so no separate copy step.
11. Grafana auth is `admin/admin` (Contract 4.2); annotation failures are non-fatal.
12. Time-to-detect is the first 2s poll that sees the alert `firing` (2s resolution; includes the alert's `for`).
13. S6 caveat: the alert `APIDown` needs `for: 15s`; a fast restart may never trigger it. Diagnosis
    (`process_restarted`) does not depend on the alert.

## Contract concerns
- Section 5.2 baseline-vs-scenario-profile conflict (decision 1); `cpu_busy` near-limit undefined (4);
  `verify` command undefined (8); no `-u/-r` in the Locust CLI contract (2).

## Dependency requests
None (stdlib, httpx, pyyaml; pytest from dev, locust from tools). Part 1 must create `cli/__init__.py`,
`tests/__init__.py`, `tests/p9_cli/__init__.py` (tests import `cli.*` from the repo root).

## Size
Code budget ~450 lines: actual **495 non-blank lines** in `cli/*.py` (run.py 155, __main__ 78, report 75,
rules 72, prom 54, jaeger 46, grafana 15) - about 10% over. Tests are extra.
