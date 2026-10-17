from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db

# auto_error=False: FastAPI's own missing-header response would not use the Contract error body.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> AppError:
    return AppError(code="unauthorized", message="Invalid or missing token", status=401)


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if creds is None:
        raise _unauthorized()
    try:
        user_id = decode_token(creds.credentials)
    except (jwt.PyJWTError, ValueError):
        raise _unauthorized() from None
    user = db.get(User, user_id)
    if user is None:  # token is valid but the account is gone
        raise _unauthorized()
    return user
