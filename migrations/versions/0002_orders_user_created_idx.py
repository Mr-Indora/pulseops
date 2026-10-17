"""index for GET /orders keyset pagination (the index scenario S4 removes and restores)

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_orders_user_created", "orders", ["user_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_index("ix_orders_user_created", table_name="orders")
