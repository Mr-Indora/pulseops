"""Fixtures for Part 3. Needs TEST_DATABASE_URL (a disposable Postgres, psycopg driver).

Nothing here drops or truncates data: migrations are applied with `upgrade head` and every
test creates its own uniquely named rows, so a shared test DB is safe to reuse.
"""
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def api():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    # Must be set before app.db.session is imported: it builds the engine at import time.
    os.environ.update(DATABASE_URL=url, MIGRATION_DATABASE_URL=url)
    os.environ.setdefault("JWT_SECRET", "p3-test-secret")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def engine(api):
    from app.db.session import engine

    return engine


@pytest.fixture
def make_user(api):
    def _make() -> dict[str, str]:
        creds = {"email": f"p3-{uuid.uuid4().hex[:12]}@example.com", "password": "p3-password"}
        assert api.post("/auth/register", json=creds).status_code == 201
        token = api.post("/auth/login", json=creds).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture
def make_product(engine):
    def _make(stock: int = 10, price: int = 250) -> int:
        sku = f"p3-{uuid.uuid4().hex[:12]}"
        with engine.begin() as conn:
            return conn.execute(
                text("INSERT INTO products (sku, name, price_cents, stock) "
                     "VALUES (:sku, :sku, :price, :stock) RETURNING id"),
                {"sku": sku, "price": price, "stock": stock},
            ).scalar_one()

    return _make


@pytest.fixture
def dead_db(api):
    """Point every get_db at an unreachable Postgres, as if the DB were down."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.session import get_db
    from app.main import app

    dead = create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x", connect_args={"connect_timeout": 1})

    def _dead_get_db():
        with Session(dead) as session:
            yield session

    app.dependency_overrides[get_db] = _dead_get_db
    yield
    app.dependency_overrides.pop(get_db)
    dead.dispose()
