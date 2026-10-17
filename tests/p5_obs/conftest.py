import logging
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, text

from app.obs.setup import setup_observability
from app.obs.tracing import get_provider


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    # File-backed SQLite uses a real QueuePool, which is what the pool gauges read. No Postgres needed.
    url = f"sqlite:///{tmp_path_factory.mktemp('db') / 'obs.db'}"
    eng = create_engine(url, pool_size=5, max_overflow=0)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO items VALUES (1, 'a'), (2, 'b')"))
    return eng


@pytest.fixture(scope="session")
def spans():
    # Unreachable collector for the whole session, set before get_provider() first reads it:
    # every test doubles as "app survives a dead OTLP endpoint".
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:9"
    exporter = InMemorySpanExporter()
    get_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def build_app(engine) -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: int):
        with engine.connect() as conn:
            row = conn.execute(text("SELECT name FROM items WHERE id = :i"), {"i": item_id}).first()
        return {"name": row[0] if row else None}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    setup_observability(app, engine)
    return app


@pytest.fixture(scope="session")
def client(engine, spans):
    # The SQLAlchemy instrumentor is a process-wide singleton: in a full-suite run an earlier test
    # file (app.main) already instrumented the app's engine, so this engine would get no DB spans.
    SQLAlchemyInstrumentor().uninstrument()
    yield TestClient(build_app(engine), raise_server_exceptions=False)
    # Stop the exporter thread and our handler before pytest closes its captured stdout.
    get_provider().shutdown()
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "_pulseops", False)]
