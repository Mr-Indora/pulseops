"""Fixtures for real-Postgres DB tests.

TEST_DATABASE_URL (postgresql+psycopg://...) must point at a throwaway database: every test
runs `alembic downgrade base` then `upgrade head`, which drops PulseOps tables in it.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture
def alembic_cfg(db_url, monkeypatch) -> Config:
    monkeypatch.setenv("MIGRATION_DATABASE_URL", db_url)
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def engine(db_url, alembic_cfg):
    """Fresh schema at head for every test (so sequences restart at 1)."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    eng = create_engine(db_url)
    yield eng
    eng.dispose()
