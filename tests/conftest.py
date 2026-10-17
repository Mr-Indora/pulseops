"""Shared fixtures. Parts 2-9 keep their own fixtures in tests/pN_*; nothing here overrides them."""
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "ci-test-pass-123"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="session")
def client(test_database_url: str) -> Iterator["TestClient"]:  # noqa: F821
    """App client on a migrated test DB (direct Postgres, no Toxiproxy)."""
    # session.py reads these at import time, so set them before importing the app.
    os.environ["DATABASE_URL"] = test_database_url
    os.environ["MIGRATION_DATABASE_URL"] = test_database_url
    os.environ.setdefault("JWT_SECRET", "test-only-secret")
    os.environ.setdefault("BCRYPT_ROUNDS", "4")

    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def seeded_user(client) -> SimpleNamespace:
    email = f"conftest-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return SimpleNamespace(
        email=email, password=PASSWORD, token=token,
        headers={"Authorization": f"Bearer {token}"},
    )
