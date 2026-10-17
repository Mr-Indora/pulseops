import json
from types import SimpleNamespace

import httpx
import pytest

from faults import injector

TOXIC_PATH = "/proxies/postgres/toxics"


class FakeToxiproxy:
    """Stateful stand-in for the Toxiproxy REST API, used via httpx.MockTransport."""

    def __init__(self):
        self.enabled, self.toxics, self.calls = True, {}, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, body = req.url.path, json.loads(req.content) if req.content else {}
        self.calls.append((req.method, path, body))
        if path == "/proxies/postgres":
            if req.method == "POST":
                self.enabled = body["enabled"]
            return httpx.Response(200, json={"name": "postgres", "enabled": self.enabled})
        if path == TOXIC_PATH:
            if req.method == "POST":
                self.toxics[body["name"]] = body
                return httpx.Response(200, json=body)
            return httpx.Response(200, json=[{"name": n} for n in self.toxics])
        removed = self.toxics.pop(path.rsplit("/", 1)[1], None)
        return httpx.Response(204 if removed else 404)


@pytest.fixture
def tp(monkeypatch):
    fake = FakeToxiproxy()
    monkeypatch.setattr(injector, "_transport", httpx.MockTransport(fake))
    return fake


@pytest.fixture
def cmds(monkeypatch):
    ran = []
    monkeypatch.setattr(injector, "_run", lambda cmd, **kw: ran.append(cmd) or SimpleNamespace(returncode=0, stderr=""))
    return ran


def test_catalogue():
    assert len(injector.list_scenarios()) == 6
    profiles = {n: injector.spec(n)["workload_profile"] for n in injector.list_scenarios()}
    assert profiles.pop("S3_pool_exhaustion") == "pool_pressure"
    assert set(profiles.values()) == {"normal"}
    with pytest.raises(ValueError):
        injector.inject("nope")


def test_s1_latency_payload_idempotent_and_recover(tp):
    injector.inject("S1_db_latency")
    injector.inject("S1_db_latency")
    assert tp.toxics == {"pulseops_latency": {
        "name": "pulseops_latency", "type": "latency", "stream": "downstream", "toxicity": 1.0,
        "attributes": {"latency": 200, "jitter": 50}}}
    injector.recover("S1_db_latency")
    injector.recover("S1_db_latency")
    assert tp.toxics == {} and tp.enabled


def test_s2_outage_cycle_also_clears_leftover_toxics(tp):
    injector.inject("S2_db_outage")
    injector.inject("S2_db_outage")
    assert not tp.enabled
    tp.toxics["stray"] = {}
    injector.recover("S2_db_outage")
    injector.recover("S2_db_outage")
    assert tp.enabled and tp.toxics == {}


def test_s3_is_a_documented_noop(tp, cmds):
    injector.inject("S3_pool_exhaustion")
    injector.recover("S3_pool_exhaustion")
    assert tp.calls == [] and cmds == []


def test_s4_downgrade_only_once_and_upgrade_to_head(monkeypatch):
    state, calls = {"head": True}, []

    def fake_alembic(*args):
        calls.append(args)
        if args == ("downgrade", "-1"):
            state["head"] = False
        if args == ("upgrade", "head"):
            state["head"] = True
        return "0002_orders_user_created_idx (head)" if state["head"] else "0001_initial"

    monkeypatch.setattr(injector, "_alembic", fake_alembic)
    injector.inject("S4_missing_index")
    injector.inject("S4_missing_index")
    assert calls.count(("downgrade", "-1")) == 1 and not state["head"]
    injector.recover("S4_missing_index")
    injector.recover("S4_missing_index")
    assert state["head"]


def test_s5_cpu_commands(cmds):
    injector.inject("S5_cpu_throttle")
    injector.recover("S5_cpu_throttle")
    assert cmds == [["docker", "update", "--cpus", "0.2", "pulseops-api"],
                    ["docker", "update", "--cpus", "1.0", "pulseops-api"]]


def test_s6_kill_then_wait_for_live(monkeypatch, cmds):
    injector.inject("S6_crash_restart")
    assert cmds == [["docker", "kill", "pulseops-api"]]
    codes = iter([httpx.ConnectError("down"), httpx.ConnectError("down"), 200])

    def fake_get(url, timeout):
        code = next(codes)
        if isinstance(code, Exception):
            raise code
        return SimpleNamespace(status_code=code)

    monkeypatch.setattr(injector.httpx, "get", fake_get)
    monkeypatch.setattr(injector, "time", SimpleNamespace(monotonic=lambda: 0, sleep=lambda s: None))
    injector.recover("S6_crash_restart")
    assert next(codes, "drained") == "drained"


def test_s6_wait_is_bounded(monkeypatch):
    def down(url, timeout):
        raise httpx.ConnectError("down")

    clock = iter(range(1000))
    monkeypatch.setattr(injector.httpx, "get", down)
    monkeypatch.setattr(injector, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    with pytest.raises(TimeoutError):
        injector.recover("S6_crash_restart")


def _toxiproxy_up() -> bool:
    try:
        httpx.get(injector.os.environ.get("TOXIPROXY_URL", "http://localhost:8474") + "/version", timeout=1)
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _toxiproxy_up(), reason="Toxiproxy not reachable")
def test_live_latency_toxic_roundtrip():
    names = lambda: [t["name"] for t in injector._tp("GET", TOXIC_PATH).json()]  # noqa: E731
    injector.inject("S1_db_latency")
    try:
        assert "pulseops_latency" in names()
    finally:
        injector.recover("S1_db_latency")
    assert names() == [] and injector._tp("GET", "/proxies/postgres").json()["enabled"]
