from datetime import datetime
from typing import Annotated

from fastapi import Path, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BIGINT = 2**63 - 1

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
# Bounded so an absurd id becomes a 422 instead of a Postgres integer-overflow 500.
PathId = Annotated[int, Path(gt=0, le=MAX_BIGINT)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OrderItemIn(_Strict):
    product_id: int = Field(gt=0, le=MAX_BIGINT)
    # le=1000 keeps price*quantity far from the int4 overflow of orders.total_cents.
    quantity: int = Field(gt=0, le=1000)


class OrderCreate(_Strict):
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_products(self) -> "OrderCreate":
        # (order_id, product_id) is the PK, so duplicates would fail at INSERT time.
        ids = [i.product_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("items must not repeat a product_id")
        return self


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductOut(_Out):
    id: int
    sku: str
    name: str
    price_cents: int
    stock: int


class OrderItemOut(_Out):
    product_id: int
    quantity: int
    unit_price_cents: int


class OrderOut(_Out):
    id: int
    status: str
    total_cents: int
    created_at: datetime
    items: list[OrderItemOut]


class TopProductOut(_Out):
    product_id: int
    sku: str
    name: str
    total_quantity: int
