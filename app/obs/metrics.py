"""Metric definitions (Contract 4.7) and SQLAlchemy engine hooks that feed them."""
import time

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import event
from sqlalchemy.engine import Engine

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)  # Contract 4.7; reused for DB histograms

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
REQUEST_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route"], buckets=BUCKETS)
IN_PROGRESS = Gauge("http_requests_in_progress", "Requests currently being handled")
POOL_SIZE = Gauge("db_pool_size", "Configured DB pool size")
POOL_CHECKED_OUT = Gauge("db_pool_checked_out", "DB connections currently in use")
CHECKOUT_WAIT = Histogram(
    "db_pool_checkout_wait_seconds", "Time to obtain a pooled DB connection", buckets=BUCKETS)
QUERY_SECONDS = Histogram(
    "db_query_duration_seconds", "DB statement latency", ["operation"], buckets=BUCKETS)


def _observe_query(statement: str, started: float) -> None:
    words = statement.split(None, 1)
    QUERY_SECONDS.labels(words[0].upper() if words else "UNKNOWN").observe(time.perf_counter() - started)


def _before(conn, cursor, statement, parameters, context, executemany) -> None:
    context._obs_started = time.perf_counter()


def _after(conn, cursor, statement, parameters, context, executemany) -> None:
    _observe_query(statement, context._obs_started)


def _on_error(ctx) -> None:
    # Failed statements (e.g. statement_timeout) are the slow ones we most want to see.
    started = getattr(ctx.execution_context, "_obs_started", None)
    if started is not None and ctx.statement:
        _observe_query(ctx.statement, started)


def bind_engine(engine: Engine) -> None:
    """Attach pool gauges and timing hooks to the engine. Safe to call repeatedly."""
    # Read engine.pool lazily: Engine.dispose() replaces the pool object.
    POOL_SIZE.set_function(lambda: engine.pool.size())
    POOL_CHECKED_OUT.set_function(lambda: engine.pool.checkedout())

    pool = engine.pool
    if not getattr(pool, "_obs_timed", False):
        original = pool.connect

        def timed_connect():
            # Pool.connect() covers queue wait, pool_pre_ping and (re)connect, and it
            # raises on pool_timeout, so exhausted-pool waits are recorded too.
            start = time.perf_counter()
            try:
                return original()
            finally:
                CHECKOUT_WAIT.observe(time.perf_counter() - start)

        pool.connect = timed_connect
        pool._obs_timed = True

    if not event.contains(engine, "before_cursor_execute", _before):
        event.listen(engine, "before_cursor_execute", _before)
        event.listen(engine, "after_cursor_execute", _after)
        event.listen(engine, "handle_error", _on_error)
