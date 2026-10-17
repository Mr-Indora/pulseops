from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Product
from app.db.session import get_db
from app.reliability.policy import retry_transient
from app.schemas import Limit, Offset, PathId, ProductOut

router = APIRouter(prefix="/products", tags=["products"])


@retry_transient
def _list(db: Session, limit: int, offset: int) -> list[ProductOut]:
    db.rollback()  # a retry must not reuse a transaction broken by the previous attempt
    rows = db.scalars(select(Product).order_by(Product.id).limit(limit).offset(offset))
    return [ProductOut.model_validate(p) for p in rows]


@retry_transient
def _get(db: Session, product_id: int) -> ProductOut | None:
    db.rollback()
    product = db.get(Product, product_id)
    return ProductOut.model_validate(product) if product else None


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), limit: Limit = 50, offset: Offset = 0):
    return _list(db, limit, offset)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: PathId, db: Session = Depends(get_db)):
    product = _get(db, product_id)
    if product is None:
        raise AppError("product_not_found", "Product not found.", 404)
    return product
