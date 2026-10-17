from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import DUMMY_HASH, create_token, hash_password, verify_password
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _norm(v: object) -> object:
    return v.strip().lower() if isinstance(v, str) else v


# BeforeValidator last so it wraps (and runs before) the length/pattern constraints.
RegisterEmail = Annotated[
    str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+$"), BeforeValidator(_norm)
]
LoginEmail = Annotated[str, Field(max_length=254), BeforeValidator(_norm)]


class RegisterIn(BaseModel):
    email: RegisterEmail
    password: str = Field(min_length=8, max_length=72)  # 72 = bcrypt's limit


class LoginIn(BaseModel):
    email: LoginEmail
    password: str = Field(max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", status_code=201, response_model=UserOut)
def register(body: RegisterIn, db: Annotated[Session, Depends(get_db)]) -> User:
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()  # the UNIQUE constraint decides duplicates: no check-then-insert race
    except IntegrityError:
        db.rollback()
        raise AppError(code="email_taken", message="Email already registered", status=409) from None
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Annotated[Session, Depends(get_db)]) -> TokenOut:
    row = db.execute(select(User.id, User.password_hash).where(User.email == body.email)).first()
    db.close()  # give the pooled connection back BEFORE bcrypt: it is CPU-bound and the pool is small
    # Always run one bcrypt verify so unknown-user and wrong-password cost the same.
    ok = verify_password(body.password, row.password_hash if row else DUMMY_HASH)
    if row is None or not ok:
        raise AppError(code="invalid_credentials", message="Invalid email or password", status=401)
    return TokenOut(access_token=create_token(row.id))
