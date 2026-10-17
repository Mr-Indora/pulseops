# Results

> **Only numbers produced by `make scenario` / `python -m cli run` runs may appear here. Empty = not measured.**

Rules: copy values from `reports/<run_id>/report.md` / `evidence.json`; one row per run; failed or not-run scenarios stay as FAIL / NOT RUN.

## Environment

| Item | Value |
|------|-------|
| Date of runs | 2026-10-17 (integration sandbox, NOT the target laptop) |
| Git commit | none (no git repo) |
| CPU / RAM / OS | 1 vCPU, ~4 GB, Ubuntu 24.04. Postgres 16, Toxiproxy 2.9.0, Prometheus 2.54.1, Jaeger 1.62.0, API (uvicorn, 1 worker) and Locust all native on the same single core. **No Docker**, no postgres-exporter, no Grafana |
| SEED_USERS / SEED_PRODUCTS | 10000 / 2000, BCRYPT_ROUNDS=10 |
| SEED_ORDERS | 20000 for the three 20 s/20 s runs; 300000 for the four 60 s/60 s runs |
| Workload | normal (20 users); S3 uses pool_pressure (40 users) |
| Phase lengths (baseline / verify) | column "base/verify s" below (detect <= 120 s, diagnose 30 s for the 60/60 runs) |

**Not representative of the target machine.** Everything shares one core, and the two seed sizes give very different baselines (see Caveats).

## Per-scenario outcome (one row per run, N=1 each)

| Scenario | run_id | base/verify s | PASS/FAIL | p95 after <= 1.2x baseline | error % after < 1% | Diagnosis == expected | Alert(s) firing at detection | time_to_detect (s) |
|---|---|---|---|---|---|---|---|---|
| S2_db_outage | 20261017-033210-S2_db_outage | 20/20 | PASS | yes | yes | yes (got DB_DOWN; expected DB_DOWN) | HighErrorRate | 42.3 |
| S1_db_latency | 20261017-033505-S1_db_latency | 20/20 | FAIL | yes | yes | no (got POOL_EXHAUSTION; expected DB_LATENCY) | DBPoolSaturated, HighLatencyP95 | 46.4 |
| S3_pool_exhaustion | 20261017-033725-S3_pool_exhaustion | 20/20 | PASS | yes | yes | yes (got POOL_EXHAUSTION; expected POOL_EXHAUSTION) | DBPoolSaturated | 37.1 |
| S4_missing_index | 20261017-033957-S4_missing_index | 20/20 | FAIL | yes | yes | no (got UNKNOWN; expected SLOW_QUERY_MISSING_INDEX) | none (expected SlowDBQueries NOT fired) | n/a |
| S1_db_latency | 20261017-034510-S1_db_latency | 60/60 | FAIL | yes | yes | no (got POOL_EXHAUSTION; expected DB_LATENCY) | DBPoolSaturated, HighLatencyP95 | 0.6 |
| S2_db_outage | 20261017-035138-S2_db_outage | 60/60 | PASS | yes | yes | yes (got DB_DOWN; expected DB_DOWN) | HighErrorRate | 42.6 |
| S3_pool_exhaustion | 20261017-035516-S3_pool_exhaustion | 60/60 | PASS | yes | yes | yes (got POOL_EXHAUSTION; expected POOL_EXHAUSTION) | DBPoolSaturated, HighLatencyP95 | 29.4 |
| S4_missing_index | 20261017-035901-S4_missing_index | 60/60 | FAIL | yes | yes | no (got POOL_EXHAUSTION; expected SLOW_QUERY_MISSING_INDEX) | HighLatencyP95 (expected SlowDBQueries NOT fired) | n/a |
| S5_cpu_throttle | | | NOT RUN | | | | | |
| S6_crash_restart | | | NOT RUN | | | | | |

## Latency and errors by phase (p50/p95/p99 in ms, rps, error %)

| Scenario | run_id | p50 base | p95 base | p99 base | p95 during | p95 after | rps base | rps during | rps after | err % base | err % during | err % after |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S2_db_outage | 20261017-033210-S2_db_outage | 10 | 60 | 93 | 229 | 64 | 63.4 | 52.6 | 64.3 | 0.00 | 100.00 | 0.00 |
| S1_db_latency | 20261017-033505-S1_db_latency | 10 | 57 | 116 | 4752 | 58 | 62.3 | 7.3 | 63.2 | 0.00 | 42.02 | 0.00 |
| S3_pool_exhaustion | 20261017-033725-S3_pool_exhaustion | 11 | 65 | 98 | 2391 | 62 | 62.5 | 41.9 | 62.6 | 0.00 | 8.18 | 0.00 |
| S4_missing_index | 20261017-033957-S4_missing_index | 9 | 49 | 88 | 50 | 46 | 65.0 | 63.3 | 63.1 | 0.00 | 0.00 | 0.00 |
| S1_db_latency | 20261017-034510-S1_db_latency | 124 | 784 | 1392 | 4752 | 859 | 39.4 | 7.4 | 38.0 | 0.00 | 45.41 | 0.00 |
| S2_db_outage | 20261017-035138-S2_db_outage | 134 | 818 | 1554 | 227 | 967 | 39.2 | 53.4 | 35.1 | 0.00 | 100.00 | 0.00 |
| S3_pool_exhaustion | 20261017-035516-S3_pool_exhaustion | 97 | 695 | 993 | 4840 | 720 | 41.7 | 18.5 | 41.6 | 0.00 | 61.10 | 0.00 |
| S4_missing_index | 20261017-035901-S4_missing_index | 113 | 843 | 1657 | 820 | 808 | 38.7 | 39.1 | 39.8 | 0.00 | 0.00 | 0.00 |

## Diagnosis evidence (from `evidence.json`)

| Scenario | run_id | p95_ratio | error_ratio | pool_util | pool_wait_p95 (s) | db_time_share | top_statement_share | db_error_spans | cpu_busy | Diagnosis returned |
|---|---|---|---|---|---|---|---|---|---|---|
| S2_db_outage | 20261017-033210-S2_db_outage | 3.836 | 1.000 | 0.200 | 0.005 | 0.000 | None | 466 | 0.460 | DB_DOWN |
| S1_db_latency | 20261017-033505-S1_db_latency | 83.559 | 0.420 | 1.000 | 2.413 | 0.157 | 0.035 | 0 | 0.050 | POOL_EXHAUSTION |
| S3_pool_exhaustion | 20261017-033725-S3_pool_exhaustion | 37.047 | 0.082 | 1.000 | 2.235 | 0.068 | 0.901 | 0 | 0.220 | POOL_EXHAUSTION |
| S4_missing_index | 20261017-033957-S4_missing_index | 1.025 | 0.000 | 1.000 | 0.005 | 0.382 | 0.318 | 0 | 0.315 | UNKNOWN |
| S1_db_latency | 20261017-034510-S1_db_latency | 6.057 | 0.454 | 1.000 | 2.413 | 0.159 | 0.041 | 0 | 0.050 | POOL_EXHAUSTION |
| S2_db_outage | 20261017-035138-S2_db_outage | 0.277 | 1.000 | 0.400 | 0.005 | 0.000 | None | 484 | 0.438 | DB_DOWN |
| S3_pool_exhaustion | 20261017-035516-S3_pool_exhaustion | 6.962 | 0.611 | 1.000 | 2.415 | 0.055 | 0.989 | 0 | 0.141 | POOL_EXHAUSTION |
| S4_missing_index | 20261017-035901-S4_missing_index | 0.972 | 0.000 | 1.000 | 0.391 | 0.318 | 0.505 | 0 | 0.204 | POOL_EXHAUSTION |

## Not run / failed

| Scenario | Status | Reason |
|---|---|---|
| S1_db_latency | FAIL (both runs) | Got `POOL_EXHAUSTION`, expected `DB_LATENCY`. +200 ms per query on a 5-connection pool saturates the pool (42-45% 5xx), so the pool rule (higher priority) matches. Not changed: re-ordering the rules on one single-core run would be overfitting. |
| S4_missing_index | FAIL (both runs) | `SlowDBQueries` never fired. 20k-order run: diagnosis `UNKNOWN`, p95 flat (50 ms during). 300k-order run: diagnosis `POOL_EXHAUSTION` (matches at baseline too), p95 843 -> 820 -> 808 ms. The missing index has no visible effect on API p95 here. |
| S5_cpu_throttle | NOT RUN | Needs `docker update`; no Docker in the sandbox. |
| S6_crash_restart | NOT RUN | Needs `docker kill`; no Docker in the sandbox. |

## Caveats (keep these true)

- N=1 per row; not benchmarks.
- **Baseline at 300k orders is already degraded** (p95 ~0.7-0.8 s, pool peak 100%, pool wait p95 ~0.4 s). `HighLatencyP95` and the pool rule are therefore already true before injection, so for the 60/60 runs `time_to_detect` is not a real detection time (S1: 0.6 s because the alert was firing at baseline). Only the S2 and S3 detect times (HighErrorRate / DBPoolSaturated, which were not firing at baseline) are meaningful, and even those are single observations.
- The 20 s/20 s runs (20k orders) have a healthy baseline (p95 ~60 ms) but very short windows.
- A first S2 60/60 attempt was cut off when the sandbox processes were killed between turns; it produced no report and is not counted.
- Five earlier pre-fix runs from the previous integration (2026-10-16) were removed from `reports/`: they ran the old login/pool code and a diagnosis bug.
- Laptop-scale stack, 100% trace sampling, demo-scale scrape/evaluation intervals (see `docs/DECISIONS.md`).
