"""Engine and session factory (Contract 4.6).

DATABASE_URL is read from os.environ, not app.core.config, to avoid an import cycle
(config -> ... -> session). Pool/timeout policy lives in app.reliability.policy.
"""

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.reliability.policy import ENGINE_OPTIONS

engine: Engine = create_engine(os.environ["DATABASE_URL"], **ENGINE_OPTIONS)
# expire_on_commit=False: routes serialise the order they just committed without a re-SELECT.
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    # Routes own commit/rollback; closing an uncommitted session rolls it back.
    with SessionLocal() as session:
        yield session
