from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.errors import AppError
from app.db.models import Order, OrderItem, Product, User
from app.db.session import get_db
from app.reliability.policy import retry_transient
from app.schemas import Limit, OrderCreate, OrderItemOut, OrderOut, PathId

router = APIRouter(prefix="/orders", tags=["orders"])


@retry_transient
def _fetch(db: Session, user_id: int, *, order_id: int | None = None,
           before: datetime | None = None, limit: int = 20) -> list[OrderOut]:
    """Own orders only (user_id is always in the WHERE), newest first, with their items."""
    db.rollback()  # a retry must not reuse a transaction broken by the previous attempt
    stmt = select(Order).where(Order.user_id == user_id)
    if order_id is not None:
        stmt = stmt.where(Order.id == order_id)
    else:
        if before is not None:
            stmt = stmt.where(Order.created_at < before)  # keyset: no OFFSET scan
        stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
    orders = db.scalars(stmt).all()
    items: dict[int, list[OrderItemOut]] = defaultdict(list)
    if orders:
        rows = db.scalars(select(OrderItem).where(OrderItem.order_id.in_([o.id for o in orders]))
                          .order_by(OrderItem.order_id, OrderItem.product_id))
        for row in rows:
            items[row.order_id].append(OrderItemOut.model_validate(row))
    return [OrderOut(id=o.id, status=o.status, total_cents=o.total_cents,
                     created_at=o.created_at, items=items[o.id]) for o in orders]


def _replay(db: Session, user_id: int, key: str) -> OrderOut | None:
    order_id = db.scalar(select(Order.id).where(Order.idempotency_key == key))
    return _fetch(db, user_id, order_id=order_id)[0] if order_id else None


def _place(db: Session, user_id: int, key: str | None, body: OrderCreate) -> int | None:
    """Runs inside the caller's single transaction. Returns None if the key was already taken."""
    total, lines = 0, []
    # Sorted ids give every transaction the same row-lock order, so no deadlocks.
    for item in sorted(body.items, key=lambda i: i.product_id):
        # Atomic check-and-decrement: no read-then-write window, so no oversell.
        price = db.scalar(
            update(Product)
            .where(Product.id == item.product_id, Product.stock >= item.quantity)
            .values(stock=Product.stock - item.quantity)
            .returning(Product.price_cents)
            .execution_options(synchronize_session=False))
        if price is None:
            if db.scalar(select(Product.id).where(Product.id == item.product_id)) is None:
                raise AppError("product_not_found", f"Product {item.product_id} not found.", 404)
            raise AppError("insufficient_stock",
                           f"Insufficient stock for product {item.product_id}.", 409)
        total += price * item.quantity
        lines.append({"product_id": item.product_id, "quantity": item.quantity,
                      "unit_price_cents": price})
    order_id = db.scalar(
        pg_insert(Order).values(user_id=user_id, total_cents=total, idempotency_key=key)
        .on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(Order.id))
    if order_id is None:
        return None
    db.execute(insert(OrderItem), [{"order_id": order_id, **line} for line in lines])
    return order_id


@router.post("", status_code=201, response_model=OrderOut)
def create_order(
    body: OrderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=128),
):
    user_id = user.id
    # The column is globally unique, so scope the key per user: one user's key can never
    # collide with, or reveal, another user's order.
    key = f"{user_id}:{idempotency_key}" if idempotency_key else None
    if key and (existing := _replay(db, user_id, key)):
        return existing
    try:
        order_id = _place(db, user_id, key, body)
        if order_id is None:  # a concurrent request with the same key won the INSERT
            db.rollback()  # undo our stock decrements
            return _replay(db, user_id, key)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _fetch(db, user_id, order_id=order_id)[0]


@router.get("", response_model=list[OrderOut])
def list_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                limit: Limit = 20, before: datetime | None = None):
    return _fetch(db, user.id, before=before, limit=limit)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: PathId, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    found = _fetch(db, user.id, order_id=order_id)
    if not found:
        raise AppError("order_not_found", "Order not found.", 404)
    return found[0]
