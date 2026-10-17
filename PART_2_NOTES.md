# PART 2 — Database: notes

## What was built
- `app/db/models.py`: typed 2.0 models for users, products, orders, order_items. Constraint names are explicit and match the migrations. No relationships. `ix_orders_user_created` is intentionally NOT in the models (only migration 0002 owns it, so S4's downgrade does not contradict them).
- `app/db/session.py`: `engine`, `SessionLocal`, `get_db()` per Contract 4.6. Reads `DATABASE_URL` from `os.environ`; imports `ENGINE_OPTIONS` from `app.reliability.policy` (Part 8). `expire_on_commit=False`, `autoflush=False`.
- `alembic.ini`, `migrations/env.py` (uses `MIGRATION_DATABASE_URL`, falls back to `HOST_DATABASE_URL`), `migrations/script.py.mako`, `versions/0001_initial.py`, `versions/0002_orders_user_created_idx.py` (ids "0001"/"0002").
- `scripts/seed.py`: generate_series bulk seed, ids 1..N so `user<N>@example.com` and product ids 1..N match the workload contract. One bcrypt hash of `loadtest-pass`, reused. Orders topped up to `SEED_ORDERS` (re-run inserts nothing), 1-5 items per order, totals set from items in a follow-up UPDATE, sequences advanced, `ANALYZE`, row counts + elapsed printed.
- `tests/p2_db/`: real-Postgres tests (skipped without `TEST_DATABASE_URL`).

## NOT VERIFIED (important)
My sandbox had no Postgres server and no network route to PyPI (pip got 403 from the egress proxy), so **nothing in this part was executed**. Only `python -m compileall` passed. Not run: ruff, pytest, alembic upgrade/downgrade, the seed, the EXPLAIN check.
Therefore the acceptance items are unconfirmed:
- upgrade -> downgrade -1 -> upgrade head: not run
- seed with SEED_ORDERS=1000 timing / idempotency: not run
- EXPLAIN plans with/without index: **not measured, no plans recorded**. Expected (unverified): index scan on `ix_orders_user_created` when present; Seq Scan + top-N Sort when dropped. The test `test_orders_plan_uses_index_only_while_it_exists` sets `enable_seqscan=off` so the result is deterministic on tiny data; for the real plans run, after `make seed`:
  `psql "$HOST_DATABASE_URL" -c "EXPLAIN (ANALYZE) SELECT * FROM orders WHERE user_id=1 ORDER BY created_at DESC LIMIT 20"` then `alembic downgrade -1` and repeat, and paste the output here.

## How to verify
```
export TEST_DATABASE_URL=postgresql+psycopg://pulseops:pulseops@localhost:5432/pulseops_test   # throwaway DB!
python -m pytest tests/p2_db -q
export MIGRATION_DATABASE_URL=$HOST_DATABASE_URL
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
SEED_ORDERS=1000 python -m scripts.seed && SEED_ORDERS=1000 python -m scripts.seed   # counts identical
```
Run from repo root (tests import `scripts.seed`; needs P1's `__init__.py` files).
The tests run `alembic downgrade base` then `upgrade head`, so they DROP PulseOps tables in `TEST_DATABASE_URL`. Never point it at the dev DB.

## Design notes
- Seeded orders do not decrement product stock (products get stock 1,000,000), so seed stays set-based and stock stays consistent for load tests.
- `BCRYPT_ROUNDS` env (default 12) at seed time sets the stored hash cost; Part 4 reads the same variable for new hashes. Lower it for load tests, since login cost is embedded in the seeded hash.
- Item product ids are deterministic per order (not random); colliding picks on tiny catalogs are dropped by the PK, so some orders have fewer than the nominal items. Totals are still exact.
- Order timestamps are spread over the last 90 days so `/stats/top-products?days=30` has a real filter.

## Code budget
~400 lines of non-test code (models 85, session 25, env 34, migrations 99, seed 118, alembic.ini 36), over the ~220 budget; much of it is docstrings/comments and the ini boilerplate. Tests add ~190.

## Contract concerns
- 4.4 `order_items` PK is unnamed in the contract; Postgres names it `order_items_pkey` and tests rely on that.
- `session.py` import-time requires `DATABASE_URL` and Part 8's `app.reliability.policy`; anything importing it without those fails at import.

## Dependency requests
None (uses sqlalchemy, psycopg, alembic, bcrypt, pytest from P1's pyproject).
