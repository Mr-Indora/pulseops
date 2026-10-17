"""Bulk seed with set-based SQL (generate_series); no per-row Python.

Idempotent: users/products use explicit ids 1..N (re-seeding users refreshes the shared password
hash, so changing BCRYPT_ROUNDS and re-running `make seed` takes effect), and orders are
topped up to SEED_ORDERS total (a re-run with enough orders inserts none). Explicit ids keep the
workload contract true: user<N>@example.com and product ids are 1..N. Sequences are advanced
afterwards so API-created rows do not collide.

Every seeded user has password "loadtest-pass". Seeded orders do not decrement stock.
BCRYPT_ROUNDS (default 12; the Makefile and .env.example set 10 for the load stack) sets the cost of the shared hash; the cost is embedded in the hash, so
a lower value at seed time makes every later login cheaper (useful on a laptop under load).
Connects directly to Postgres via HOST_DATABASE_URL (never through the fault-injection proxy).
"""

import os
import time

import bcrypt
from sqlalchemy import create_engine, text

PASSWORD = b"loadtest-pass"

USERS_SQL = text(
    """
    INSERT INTO users (id, email, password_hash)
    SELECT g, 'user' || g || '@example.com', CAST(:hash AS text)
    FROM generate_series(1, CAST(:n AS int)) AS g
    ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash
    """
)

PRODUCTS_SQL = text(
    """
    INSERT INTO products (id, sku, name, price_cents, stock)
    SELECT g, 'SKU-' || lpad(g::text, 6, '0'), 'Product ' || g, 100 + (g * 37) % 9900, 1000000
    FROM generate_series(1, CAST(:n AS int)) AS g
    ON CONFLICT DO NOTHING
    """
)

# Orders and items in one statement (items read the new order ids via RETURNING). Totals cannot be
# set here: a sibling CTE's rows are invisible to an UPDATE in the same statement, see TOTALS_SQL.
# Item product ids are deterministic per order; collisions on tiny catalogs are dropped by the PK.
ORDERS_SQL = text(
    """
    WITH new_orders AS (
        INSERT INTO orders (user_id, status, total_cents, created_at)
        SELECT 1 + floor(random() * CAST(:users AS int))::int,
               (ARRAY['pending','paid','shipped','cancelled'])[1 + floor(random() * 4)::int],
               0,
               now() - random() * interval '90 days'
        FROM generate_series(1, CAST(:missing AS int))
        RETURNING id
    )
    INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents)
    SELECT o.id, p.id, (1 + o.id % 3)::int, p.price_cents
    FROM new_orders o
    CROSS JOIN LATERAL generate_series(1, (1 + o.id % 5)::int) AS k(n)
    JOIN products p ON p.id = 1 + (o.id * 31 + k.n * 977) % CAST(:products AS bigint)
    ON CONFLICT DO NOTHING
    """
)

TOTALS_SQL = text(
    """
    UPDATE orders o SET total_cents = s.total
    FROM (
        SELECT order_id, sum(quantity * unit_price_cents) AS total
        FROM order_items WHERE order_id > :before GROUP BY order_id
    ) s
    WHERE o.id = s.order_id AND o.id > :before
    """
)

TABLES = ("users", "products", "orders", "order_items")


def seed(url: str, users: int, products: int, orders: int) -> dict[str, int]:
    rounds = int(os.environ.get("BCRYPT_ROUNDS", "12"))
    pw_hash = bcrypt.hashpw(PASSWORD, bcrypt.gensalt(rounds)).decode()  # one hash for all rows
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(USERS_SQL, {"n": users, "hash": pw_hash})
            conn.execute(PRODUCTS_SQL, {"n": products})
            for table in ("users", "products"):
                conn.execute(
                    text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                         f"(SELECT max(id) FROM {table}))")
                )
            missing = orders - conn.execute(text("SELECT count(*) FROM orders")).scalar_one()
            if missing > 0:
                before = conn.execute(text("SELECT coalesce(max(id), 0) FROM orders")).scalar_one()
                conn.execute(ORDERS_SQL, {"users": users, "products": products, "missing": missing})
                conn.execute(TOTALS_SQL, {"before": before})
        with engine.begin() as conn:
            conn.execute(text("ANALYZE"))
            return {
                t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES
            }
    finally:
        engine.dispose()


def main() -> None:
    started = time.perf_counter()
    counts = seed(
        os.environ["HOST_DATABASE_URL"],
        int(os.environ.get("SEED_USERS", "10000")),
        int(os.environ.get("SEED_PRODUCTS", "2000")),
        int(os.environ.get("SEED_ORDERS", "300000")),
    )
    for table, n in counts.items():
        print(f"{table}: {n}")
    print(f"elapsed: {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
