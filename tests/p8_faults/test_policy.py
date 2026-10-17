import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.reliability import policy


def _op_error(sqlstate=None):
    return OperationalError("SELECT 1", {}, SimpleNamespace(sqlstate=sqlstate))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(policy, "time", SimpleNamespace(sleep=lambda s: None))


def test_engine_options_from_env(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "1500")
    opts = importlib.reload(policy).ENGINE_OPTIONS
    assert opts["pool_size"] == 7 and opts["max_overflow"] == 0 and opts["pool_pre_ping"]
    assert opts["connect_args"] == {"connect_timeout": 3, "options": "-c statement_timeout=1500"}


@pytest.mark.parametrize(("failures", "calls", "raises"), [(2, 3, False), (3, 3, True)])
def test_retry_limits(failures, calls, raises):
    n = {"c": 0}

    @policy.retry_transient
    def read():
        n["c"] += 1
        if n["c"] <= failures:
            raise _op_error()
        return "ok"

    if raises:
        with pytest.raises(OperationalError):
            read()
    else:
        assert read() == "ok"
    assert n["c"] == calls


@pytest.mark.parametrize("exc", [ValueError("x"), _op_error("57014")])
def test_no_retry_for_other_errors_or_statement_timeout(exc):
    n = {"c": 0}

    @policy.retry_transient
    def read():
        n["c"] += 1
        raise exc

    with pytest.raises(type(exc)):
        read()
    assert n["c"] == 1


def test_map_db_error():
    assert policy.map_db_error(_op_error()) == (503, "db_unavailable")
    assert policy.map_db_error(_op_error("57014")) == (503, "db_unavailable")
    assert policy.map_db_error(PoolTimeoutError("pool")) == (503, "db_pool_timeout")
    assert policy.map_db_error(KeyError("x")) == (500, "internal_error")
