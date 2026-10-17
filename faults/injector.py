"""Real fault injection for the six PulseOps scenarios (Contract 4.6).

inject() and recover() are idempotent: calling either twice is safe. recover() undoes exactly
what inject() did, so an inject -> recover cycle returns to baseline (no toxics, proxy enabled,
cpus restored, alembic at head). S3 is load-driven: both functions are documented no-ops.
"""
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from functools import cache
from pathlib import Path

import httpx
import yaml

FAULTS_DIR = Path(__file__).resolve().parent
ROOT = FAULTS_DIR.parent
PROXY = "postgres"
TOXIC = "pulseops_latency"
CONTAINER = "pulseops-api"
DEFAULT_HOST_DB = "postgresql+psycopg://pulseops:pulseops@localhost:5432/pulseops"

_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport here


@cache
def _scenarios() -> dict[str, dict]:
    data = yaml.safe_load((FAULTS_DIR / "scenarios.yaml").read_text())
    return {s["id"]: s for s in data["scenarios"]}


def list_scenarios() -> list[str]:
    return list(_scenarios())


def spec(name: str) -> dict:
    if name not in _scenarios():
        raise ValueError(f"unknown scenario {name!r}; known: {list_scenarios()}")
    return dict(_scenarios()[name])


# --- plumbing -------------------------------------------------------------------------------
def _tp(method: str, path: str, ok: tuple[int, ...] = (200, 201, 204), **kw) -> httpx.Response:
    url = os.environ.get("TOXIPROXY_URL", "http://localhost:8474")
    with httpx.Client(base_url=url, timeout=5, transport=_transport) as client:
        resp = client.request(method, path, **kw)
    if resp.status_code not in ok:
        raise RuntimeError(f"toxiproxy {method} {path} -> {resp.status_code}: {resp.text}")
    return resp


def _run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)
    if check and res.returncode:
        raise RuntimeError(f"{' '.join(cmd)} failed: {res.stderr.strip()}")
    return res


def _alembic(*args: str) -> str:
    # alembic runs on the host, so it must reach Postgres directly (not via the proxy).
    env = {**os.environ, "MIGRATION_DATABASE_URL": os.environ.get("HOST_DATABASE_URL", DEFAULT_HOST_DB)}
    res = _run([sys.executable, "-m", "alembic", *args], env=env, cwd=ROOT)
    return res.stdout + res.stderr


# --- toxiproxy ------------------------------------------------------------------------------
def _ensure_proxy() -> None:
    if _tp("GET", f"/proxies/{PROXY}", ok=(200, 404)).status_code == 404:
        _tp("POST", "/proxies", json=json.loads((FAULTS_DIR / "toxiproxy.json").read_text())[0])


def _set_enabled(enabled: bool) -> None:
    _tp("POST", f"/proxies/{PROXY}", json={"enabled": enabled})


def _restore_proxy(_: dict) -> None:
    _ensure_proxy()
    for toxic in _tp("GET", f"/proxies/{PROXY}/toxics").json():
        _tp("DELETE", f"/proxies/{PROXY}/toxics/{toxic['name']}", ok=(204, 404))
    _set_enabled(True)


def _add_latency(p: dict) -> None:
    _ensure_proxy()
    _tp("DELETE", f"/proxies/{PROXY}/toxics/{TOXIC}", ok=(204, 404))  # replace, never stack
    body = {"name": TOXIC, "type": "latency", "stream": "downstream", "toxicity": 1.0,
            "attributes": {"latency": p["latency_ms"], "jitter": p["jitter_ms"]}}
    _tp("POST", f"/proxies/{PROXY}/toxics", json=body)


def _disable_proxy(_: dict) -> None:
    _ensure_proxy()
    _set_enabled(False)


# --- docker / alembic -----------------------------------------------------------------------
def _set_cpus(cpus: float) -> None:
    _run(["docker", "update", "--cpus", str(cpus), CONTAINER])


def _kill_api(_: dict) -> None:
    res = _run(["docker", "kill", CONTAINER], check=False)
    if res.returncode and "is not running" not in res.stderr:  # already dead = already injected
        raise RuntimeError(f"docker kill failed: {res.stderr.strip()}")


def _wait_live(p: dict) -> None:
    url = os.environ.get("PULSEOPS_API_URL", "http://localhost:8000") + "/health/live"
    deadline = time.monotonic() + p["wait_live_s"]
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(f"{url} not healthy within {p['wait_live_s']}s after kill")


def _drop_index(_: dict) -> None:
    if "(head)" in _alembic("current"):  # guard: a second downgrade -1 would drop 0001 too
        _alembic("downgrade", "-1")


def _noop(_: dict) -> None:
    """S3 is load-driven (pool_pressure workload vs a 5-connection pool): nothing to inject or undo."""


_INJECT: dict[str, Callable[[dict], None]] = {
    "S1_db_latency": _add_latency,
    "S2_db_outage": _disable_proxy,
    "S3_pool_exhaustion": _noop,
    "S4_missing_index": _drop_index,
    "S5_cpu_throttle": lambda p: _set_cpus(p["cpus"]),
    "S6_crash_restart": _kill_api,
}
_RECOVER: dict[str, Callable[[dict], None]] = {
    "S1_db_latency": _restore_proxy,
    "S2_db_outage": _restore_proxy,
    "S3_pool_exhaustion": _noop,
    "S4_missing_index": lambda _: _alembic("upgrade", "head"),
    "S5_cpu_throttle": lambda p: _set_cpus(p["restore_cpus"]),
    "S6_crash_restart": _wait_live,
}


def inject(name: str) -> None:
    params = spec(name)["params"]  # spec() first: unknown names raise a clear ValueError
    _INJECT[name](params)


def recover(name: str) -> None:
    params = spec(name)["params"]
    _RECOVER[name](params)
