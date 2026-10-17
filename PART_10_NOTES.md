# PART_10_NOTES — Quality & Docs

## What was built
`tests/conftest.py`, `tests/e2e/{conftest.py,test_stack.py}`, `.github/workflows/ci.yml`, `README.md`,
`docs/{ARCHITECTURE,DECISIONS,DEFENCE,RESULTS,CV_BULLETS}.md`, `docs/runbooks/S1..S6`.
`docs/RESULTS.md` is an empty template; no measured numbers exist anywhere in this part.

## How it was verified
- `ruff check` on `tests/` and `python -m compileall tests`: pass.
- `ci.yml`: parsed with PyYAML and checked with actionlint: pass.
- NOT run (no stack, no other parts' code in this sandbox): `pytest tests/e2e`, the `client`/`seeded_user` fixtures, the CI jobs on GitHub, the mermaid diagram rendering.

## Assumptions about other parts (please check at integration)
- `pyproject.toml` exposes extras `dev` and `tools` (`pip install -e ".[dev,tools]"`). If P1 used PEP 735 `[dependency-groups]`, change the install lines in `ci.yml`.
- `alembic.ini` + `migrations/` at repo root; `tests/conftest.py` sets `script_location` explicitly and `DATABASE_URL`/`MIGRATION_DATABASE_URL` before importing `app.main`.
- `python -m cli run <id> --baseline N --verify N` writes `reports/<run_id>/report.md` where the first PASS/FAIL word after a "Summary" heading is the verdict (the e2e S2 test parses that, not the exit code).
- `make up` starts the stack, `make seed` reads `SEED_ORDERS` from the environment, `make down` stops it (e2e job in `ci.yml`); the e2e job appends `JWT_SECRET` to `.env`.
- Jaeger query API accepts `lookback=5m` on `/api/traces`; spans carry `db.system=postgresql` and `references` for children.
- Runbook/DEFENCE pointers to `PART_N_NOTES.md` assume those notes are merged into the repo root.

## Contract concerns
- Contract does not state the CLI exit code or the exact `report.md` heading format; the e2e test is tolerant but depends on the assumption above.
- Contract 4.3 lists no `BCRYPT_ROUNDS`, but P4's prompt introduces it; `conftest.py` and `ci.yml` set it for speed.

## Dependency requests
None. Uses pytest, httpx, alembic, fastapi (TestClient) already in the runtime/dev groups.
