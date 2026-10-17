import os
from typing import Annotated

import pytest

# Set before any test module imports app.auth.* (JWT_SECRET is read at import; rounds=4 is fast).
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-anywhere-else-0123456789")
os.environ.setdefault("BCRYPT_ROUNDS", "4")
TEST_DB = os.environ.get("TEST_DATABASE_URL")
# app.db.session builds its engine at import; it connects lazily, so a placeholder is harmless.
os.environ.setdefault("DATABASE_URL", TEST_DB or "postgresql+psycopg://x:x@localhost:5432/x")


@pytest.fixture(scope="session")
def session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import User

    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_engine(TEST_DB)
    User.__table__.create(engine, checkfirst=True)  # never dropped: the DB may be shared
    yield sessionmaker(engine)
    engine.dispose()


@pytest.fixture
def client(session_factory):
    from fastapi import Depends, FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from app.auth.deps import get_current_user
    from app.auth.router import router
    from app.core.errors import AppError
    from app.db.models import User
    from app.db.session import get_db

    # Minimal app: only the auth router plus one protected route. Tests use unique emails
    # instead of truncating, so they cannot clobber other parts' rows.
    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(AppError)
    async def _handler(request, exc: AppError):
        body = {"error": {"code": exc.code, "message": exc.message, "request_id": None}}
        return JSONResponse(status_code=exc.status, content=body)

    @app.get("/_protected")
    def protected(user: Annotated[User, Depends(get_current_user)]):
        return {"id": user.id, "email": user.email}

    def _db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app)
