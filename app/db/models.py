"""Typed models mirroring Contract 4.4.

Alembic migrations are the schema source of truth. The orders(user_id, created_at DESC) index is
deliberately NOT declared here: it lives only in migration 0002 so scenario S4 can drop it
without the models claiming it exists.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        CheckConstraint("price_cents >= 0", name="ck_products_price_nonneg"),
        CheckConstraint("stock >= 0", name="ck_products_stock_nonneg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sku: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','paid','shipped','cancelled')", name="ck_orders_status"
        ),
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", name="fk_orders_user"))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    total_cents: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        Index("ix_order_items_product", "product_id"),
    )

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", name="fk_order_items_order"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", name="fk_order_items_product"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
