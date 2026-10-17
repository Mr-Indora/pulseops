"""DB reliability policy (Contract 4.6). Reads os.environ only, by contract."""
import os
import random
import time
from collections.abc import Callable
from functools import wraps

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

MAX_RETRIES = 2
BACKOFF_BASE_S = 0.05
STATEMENT_TIMEOUT_SQLSTATE = "57014"  # query_canceled

ENGINE_OPTIONS: dict = {
    "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
    "max_overflow": 0,  # hard cap: exhaustion must be visible (S3), not absorbed
    "pool_timeout": float(os.environ.get("DB_POOL_TIMEOUT", "2")),
    "pool_pre_ping": True,  # lets the pool recover after an outage without an API restart (S2)
    "connect_args": {
        "connect_timeout": 3,
        "options": f"-c statement_timeout={int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', '3000'))}",
    },
}


def _is_statement_timeout(exc: BaseException) -> bool:
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == STATEMENT_TIMEOUT_SQLSTATE


def retry_transient[F: Callable](fn: F) -> F:
    """Retry `fn` up to MAX_RETRIES times on OperationalError, with exponential backoff + full jitter.

    ONLY for IDEMPOTENT READS. Never wrap writes: a commit that failed after reaching the
    server would be replayed. Statement timeouts are not retried: repeating a query that just
    ran for the full timeout multiplies load on an already struggling DB (retry storm).
    The final error is always re-raised.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except OperationalError as exc:
                if attempt == MAX_RETRIES or _is_statement_timeout(exc):
                    raise
                time.sleep(random.uniform(0, BACKOFF_BASE_S * 2**attempt))

    return wrapper  # type: ignore[return-value]


def map_db_error(exc: BaseException) -> tuple[int, str]:
    """Map a DB exception to (http_status, error_code). Statement timeouts are OperationalErrors."""
    if isinstance(exc, PoolTimeoutError):
        return 503, "db_pool_timeout"
    if isinstance(exc, OperationalError | InterfaceError):
        return 503, "db_unavailable"
    return 500, "internal_error"
