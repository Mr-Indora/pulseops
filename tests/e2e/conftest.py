"""E2E fixtures: every one skips (not fails) when its target is unreachable."""
import os
import uuid

import httpx
import pytest

API = os.environ.get("PULSEOPS_API_URL", "http://localhost:8000")
PROM = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
JAEGER = os.environ.get("JAEGER_URL", "http://localhost:16686")


def _probe(url: str) -> None:
    try:
        httpx.get(url, timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"stack not reachable: {url}")


@pytest.fixture(scope="session")
def api():
    _probe(f"{API}/health/ready")
    with httpx.Client(base_url=API, timeout=10) as c:
        yield c


@pytest.fixture(scope="session")
def prom_url() -> str:
    _probe(f"{PROM}/-/ready")
    return PROM


@pytest.fixture(scope="session")
def jaeger_url() -> str:
    _probe(f"{JAEGER}/api/services")
    return JAEGER


@pytest.fixture
def headers(api) -> dict[str, str]:
    email, pw = f"e2e-{uuid.uuid4().hex[:8]}@example.com", "e2e-pass-12345"
    assert api.post("/auth/register", json={"email": email, "password": pw}).status_code == 201
    r = api.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
