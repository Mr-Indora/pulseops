# PART 8 — Reliability & Faults

## Built
- `app/reliability/policy.py`: ENGINE_OPTIONS, `retry_transient`, `map_db_error` (Contract 4.6).
- `faults/toxiproxy.json`: proxy `postgres` 0.0.0.0:5433 -> postgres:5432 (toxiproxy `-config` array format).
- `faults/scenarios.yaml`: top-level key `scenarios:` (list). Each has id, description, workload_profile,
  expected_alert, expected_diagnosis, fix_description, params. `injector.spec(name)` returns one entry
  as a dict (including `params`).
- `faults/injector.py`: `list_scenarios / inject / recover / spec`.
- `tests/p8_faults/`: injector + policy unit tests, one optional live-Toxiproxy test.

## Behaviour worth knowing
- recover(X) undoes exactly what inject(X) did (S1/S2: delete ALL toxics, ensure proxy exists, enable it;
  S4: `alembic upgrade head`; S5: `--cpus` from `params.restore_cpus`; S6: wait on /health/live,
  bounded by `params.wait_live_s`, raises TimeoutError). S3 inject/recover are documented no-ops.
- S4 inject downgrades only if `alembic current` shows `(head)`, so a second inject cannot drop 0001.
- alembic is run as `python -m alembic` from the repo root with MIGRATION_DATABASE_URL set to
  HOST_DATABASE_URL (default localhost:5432).
- `retry_transient` does NOT retry statement timeouts (SQLSTATE 57014) — a retry-storm guard. This is a subset
  of "only OperationalError", so it stays within the Contract.

## Verified (and not)
- Real services were NOT available: no network, no Docker, no Postgres, and httpx/sqlalchemy/pytest were not installable.
- I ran the test files under a throwaway stub harness (fake httpx/sqlalchemy.exc/pytest, not shipped):
  14 passed, 1 skipped (live test). That checks logic, not compatibility with the real libraries.
- NOT verified: real Toxiproxy/docker/alembic calls, real pytest/ruff runs.

## Verify on your machine
    make up && make migrate
    pytest tests/p8_faults -q
    python - <<'PY'
    from faults import injector as i
    for s in i.list_scenarios():
        i.inject(s); i.inject(s); i.recover(s); i.recover(s)
    PY
    curl -s localhost:8474/proxies/postgres/toxics          # expect []
    curl -s localhost:8474/proxies/postgres | grep -o '"enabled":[a-z]*'   # expect true
    docker inspect -f '{{.HostConfig.NanoCpus}}' pulseops-api              # expect 1000000000
    python -m alembic current                               # expect (head)  (MIGRATION_DATABASE_URL=localhost)

## Contract concerns
- `expected_alert` is a single string, but Blueprint 5.1 lists two for S4 (SlowDBQueries / HighLatencyP95) and
  S6 (APIDown / HighErrorRate). I chose SlowDBQueries and APIDown. With 5s scrape and `for: 15s`, APIDown may
  not fire for a fast restart; Part 9 may need to accept the alternates.
- Test files use `from faults import injector` / `from app.reliability import policy`; this needs P1's empty `__init__.py` files.

## Dependency requests
httpx, PyYAML, SQLAlchemy (runtime); pytest (dev). Alembic must be installed on the host for S4.
