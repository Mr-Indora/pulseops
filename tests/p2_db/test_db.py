import bcrypt
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from scripts.seed import seed

ORDERS_IDX = "ix_orders_user_created"
ITEMS_IDX = "ix_order_items_product"


def index_names(engine) -> set[str]:
    sql = text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(sql)}


def test_downgrade_removes_only_orders_index(engine, alembic_cfg):
    assert {ORDERS_IDX, ITEMS_IDX} <= index_names(engine)
    command.downgrade(alembic_cfg, "-1")
    names = index_names(engine)
    assert ORDERS_IDX not in names and ITEMS_IDX in names
    assert {"users", "products", "orders", "order_items"} <= set(inspect(engine).get_table_names())
    command.upgrade(alembic_cfg, "head")
    assert ORDERS_IDX in index_names(engine)


@pytest.fixture
def base(engine):
    # No explicit ids: sequences are fresh, so the first rows get id 1 (and 2 for products).
    with engine.begin() as conn:
        for stmt in (
            "INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'h')",
            "INSERT INTO products (sku, name, price_cents, stock) VALUES ('p1', 'p', 100, 5)",
            "INSERT INTO products (sku, name, price_cents, stock) VALUES ('p2', 'p', 100, 5)",
            "INSERT INTO orders (user_id, total_cents, idempotency_key) VALUES (1, 100, 'k1')",
            "INSERT INTO order_items VALUES (1, 1, 1, 100)",
        ):
            conn.execute(text(stmt))


# name -> (statement, name of the constraint that must be the one rejecting it)
BAD_ROWS = {
    "negative_stock": (
        "INSERT INTO products (sku, name, price_cents, stock) VALUES ('s', 'n', 1, -1)",
        "ck_products_stock_nonneg",
    ),
    "negative_price": (
        "INSERT INTO products (sku, name, price_cents, stock) VALUES ('s', 'n', -1, 1)",
        "ck_products_price_nonneg",
    ),
    "duplicate_email": (
        "INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'h')",
        "uq_users_email",
    ),
    "duplicate_sku": (
        "INSERT INTO products (sku, name, price_cents, stock) VALUES ('p1', 'n', 1, 1)",
        "uq_products_sku",
    ),
    "bad_status": (
        "INSERT INTO orders (user_id, status, total_cents) VALUES (1, 'lost', 0)",
        "ck_orders_status",
    ),
    "unknown_user": (
        "INSERT INTO orders (user_id, total_cents) VALUES (999, 0)",
        "fk_orders_user",
    ),
    "duplicate_idempotency_key": (
        "INSERT INTO orders (user_id, total_cents, idempotency_key) VALUES (1, 0, 'k1')",
        "uq_orders_idempotency_key",
    ),
    "zero_quantity": (
        "INSERT INTO order_items VALUES (1, 2, 0, 100)",
        "ck_order_items_quantity_positive",
    ),
    "duplicate_item": (
        "INSERT INTO order_items VALUES (1, 1, 1, 100)",
        "order_items_pkey",
    ),
    "unknown_product": (
        "INSERT INTO order_items VALUES (1, 999, 1, 100)",
        "fk_order_items_product",
    ),
}


@pytest.mark.parametrize("sql,constraint", BAD_ROWS.values(), ids=BAD_ROWS.keys())
def test_constraint_rejects_bad_row(engine, base, sql, constraint):
    with pytest.raises(IntegrityError) as exc, engine.begin() as conn:
        conn.execute(text(sql))
    assert exc.value.orig.diag.constraint_name == constraint


def test_defaults_and_multiple_null_idempotency_keys(engine, base):
    with engine.begin() as conn:
        for _ in range(2):
            conn.execute(text("INSERT INTO orders (user_id, total_cents) VALUES (1, 0)"))
        row = conn.execute(
            text("SELECT status, created_at IS NOT NULL FROM orders ORDER BY id DESC LIMIT 1")
        ).one()
    assert tuple(row) == ("pending", True)


MISMATCHED_TOTALS = """
SELECT count(*) FROM orders o
WHERE o.total_cents <> COALESCE(
    (SELECT sum(quantity * unit_price_cents) FROM order_items WHERE order_id = o.id), 0)
"""


@pytest.mark.parametrize("users,products,orders", [(20, 10, 100), (5, 3, 50)])
def test_seed_is_consistent_and_idempotent(engine, db_url, monkeypatch, users, products, orders):
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    first = seed(db_url, users, products, orders)
    assert (first["users"], first["products"], first["orders"]) == (users, products, orders)
    assert first["order_items"] > 0
    assert seed(db_url, users, products, orders) == first  # re-run adds nothing

    with engine.begin() as conn:
        assert conn.execute(text(MISMATCHED_TOTALS)).scalar_one() == 0
        stored = conn.execute(
            text("SELECT password_hash FROM users WHERE email = 'user1@example.com'")
        ).scalar_one()
        # Sequences were advanced past the explicit seed ids, so normal inserts must not collide.
        conn.execute(
            text("INSERT INTO users (email, password_hash) VALUES ('new@example.com', 'h')")
        )
        conn.execute(
            text("INSERT INTO products (sku, name, price_cents, stock) VALUES ('new', 'n', 1, 1)")
        )
    assert bcrypt.checkpw(b"loadtest-pass", stored.encode())


ORDERS_QUERY = "EXPLAIN SELECT * FROM orders WHERE user_id = 1 ORDER BY created_at DESC LIMIT 20"


def plan(engine) -> str:
    # enable_seqscan=off makes the plan deterministic on small test data: it shows whether the
    # index is available at all, not what the planner would pick at production-like row counts.
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        return "\n".join(r[0] for r in conn.execute(text(ORDERS_QUERY)))


def test_orders_plan_uses_index_only_while_it_exists(engine, alembic_cfg, db_url, monkeypatch):
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    seed(db_url, 50, 20, 2000)
    assert ORDERS_IDX in plan(engine)
    command.downgrade(alembic_cfg, "-1")
    without = plan(engine)
    assert ORDERS_IDX not in without and "Sort" in without
