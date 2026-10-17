"""initial schema (Contract 4.4)

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        _created_at(),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("sku", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("stock", sa.Integer, nullable=False),
        _created_at(),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
        sa.CheckConstraint("price_cents >= 0", name="ck_products_price_nonneg"),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock_nonneg"),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("total_cents", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_orders_user"),
        sa.CheckConstraint(
            "status IN ('pending','paid','shipped','cancelled')", name="ck_orders_status"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_cents", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("order_id", "product_id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_order_items_order"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_order_items_product"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
    )
    op.create_index("ix_order_items_product", "order_items", ["product_id"])


def downgrade() -> None:
    # Dropping order_items also drops ix_order_items_product.
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")
    op.drop_table("users")
