from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Order, OrderItem, Product
from app.db.session import get_db
from app.reliability.policy import retry_transient
from app.schemas import Limit, TopProductOut

router = APIRouter(prefix="/stats", tags=["stats"])


@retry_transient
def _top_products(db: Session, days: int, limit: int) -> list[TopProductOut]:
    db.rollback()
    total = func.sum(OrderItem.quantity)
    # One deliberately heavy aggregate: it is the S3 pool-pressure workload.
    stmt = (
        select(Product.id.label("product_id"), Product.sku, Product.name,
               total.label("total_quantity"))
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.created_at >= func.now() - timedelta(days=days))
        .group_by(Product.id)
        .order_by(total.desc())
        .limit(limit)
    )
    return [TopProductOut.model_validate(r) for r in db.execute(stmt)]


@router.get("/top-products", response_model=list[TopProductOut])
def top_products(
    db: Session = Depends(get_db),
    days: Annotated[int, Query(ge=1, le=3650)] = 30,
    limit: Limit = 10,
):
    return _top_products(db, days, limit)
