# PART 3 — API Core: notes

## What was built
`app/main.py`, `app/core/config.py`, `app/core/errors.py`, `app/schemas.py`,
`app/api/{products,orders,stats,health}.py`, `tests/p3_api/**`. No service/repository layers.

## Verification status (read this first)
**Nothing was executed against Postgres or FastAPI.** The authoring sandbox had no network, no
Postgres and no FastAPI install. What was actually done: `python -m py_compile` on every file (passes).
The tests have never been run. Expect to fix small things on first run.

To verify (needs Parts 1, 2, 4, 5, 8 merged and a throwaway Postgres):
    export TEST_DATABASE_URL=postgresql+psycopg://pulseops:pulseops@localhost:5432/pulseops_test
    python -m pytest tests/p3_api -q
`test_errors.py` needs no DB. Everything else is skipped if `TEST_DATABASE_URL` is unset.
Tests never drop/truncate; they run `alembic upgrade head` and create uniquely named rows.

## Design points worth defending
- Stock: `UPDATE products SET stock = stock - :q WHERE id=:id AND stock>=:q RETURNING price_cents`
  per item, in ascending product_id order, one transaction; 0 rows -> 404 (product missing) or 409.
  The unit price comes from the same statement, so price and decrement cannot disagree.
- Idempotency: stored key is `"<user_id>:<Idempotency-Key>"` (column is globally unique; scoping stops
  cross-user collisions/leaks). Early lookup, plus `INSERT ... ON CONFLICT DO NOTHING` so two concurrent
  requests with the same key yield one order: the loser rolls back its stock decrements and returns the winner.
- Reads: each is a small `@retry_transient` helper (not the route function itself, so FastAPI's signature
  inspection is never affected). Each starts with `db.rollback()` because a retry must not reuse a
  transaction broken by the failed attempt. They receive plain ints (`user.id` read beforehand) since rollback
  expires ORM instances. Writes are never retried.
- `/health/ready` bounds the query with a transaction-local `statement_timeout` (1000 ms, `READY_TIMEOUT_MS`).

## Assumptions about other parts (verify at integration)
- `app.db.models` exposes `User, Product, Order, OrderItem` with attributes named exactly like the Contract 4.4
  columns, and `orders.status` has a default (the INSERT omits it).
- `get_current_user` raises 401 via HTTPException or AppError (both end up in the Contract error body).
- `retry_transient` preserves the wrapped function's return value and re-raises non-retryable errors untouched.
- `map_db_error` returns codes only from {db_unavailable, db_pool_timeout, internal_error}
  (errors.py indexes a message dict with the code; a new code would raise KeyError).
- `get_db` does not open an explicit transaction (I call `commit()/rollback()` myself, never `db.begin()`).

## Contract concerns
1. Idempotent replay returns **201** (same as first call), not 200, to stay with the table in 4.5.
2. `GET /orders` keyset uses `created_at` alone, as specified. Two orders with an identical timestamp
   at a page boundary could be skipped; timestamps differ in practice because each order is its own transaction.
3. The 1 s readiness bound covers query execution only. Waiting for a pooled connection (`DB_POOL_TIMEOUT`, 2 s)
   or connecting (`connect_timeout`, 3 s) is bounded by Part 8's settings, so a saturated pool can make
   `/health/ready` take up to ~2 s before it returns 503.
4. I added bounds not in the Contract: `quantity <= 1000`, ids <= bigint max, `days <= 3650`, Idempotency-Key
   <= 128 chars, duplicate product_ids in one order rejected (422). They turn would-be DB overflow/PK errors into 422.
5. Unhandled exceptions: Starlette's ServerErrorMiddleware sits outside Part 5's middleware, so Part 5 must
   decide how a 500 from the `Exception` handler is counted/logged.

## Unverified implementation risks
- `func.now() - timedelta(days=...)` in stats and ORM `update(...).returning(...)` /
  `pg_insert(...).on_conflict_do_nothing(index_elements=["idempotency_key"])` follow SQLAlchemy 2.x docs but were not run.
- The threaded tests assume the default pool (5) tolerates 10 short concurrent requests within `DB_POOL_TIMEOUT`;
  a 503 there would show as a test failure, which is intentional (it is not an oversell, but it is worth knowing).

## Dependency requests
None beyond Part 1's list (tests use pytest, httpx via TestClient, alembic, sqlalchemy).

## Size
~380 lines of app code including blank lines (budget ~350).
