import os
from types import SimpleNamespace

import pytest

# Importing locust monkey-patches the whole process with gevent, which deadlocks the TestClient/DB
# threads of every test that runs after it in a full-suite run. Skip the patch for this import
# only (the env var must not leak: the smoke test's Locust subprocess inherits os.environ).
os.environ["LOCUST_SKIP_MONKEY_PATCH"] = "1"
try:
    pytest.importorskip("locust")
    locustfile = pytest.importorskip("workload.locustfile")
finally:
    del os.environ["LOCUST_SKIP_MONKEY_PATCH"]

from workload.profiles import PROFILES, TASK_ROUTES  # noqa: E402


def test_every_task_has_a_handler():
    for key in TASK_ROUTES:
        assert callable(getattr(locustfile.PulseOpsUser, f"do_{key}"))


def test_order_payload_has_1_to_3_distinct_valid_products():
    for _ in range(200):
        items = locustfile.order_payload()["items"]
        ids = [i["product_id"] for i in items]
        assert 1 <= len(ids) <= 3
        assert len(set(ids)) == len(ids)
        assert all(1 <= i <= locustfile.SEED_PRODUCTS for i in ids)
        assert all(i["quantity"] > 0 for i in items)


def _env(profile, users, rate):
    return SimpleNamespace(parsed_options=SimpleNamespace(
        profile=profile, num_users=users, spawn_rate=rate))


def test_profile_sets_load_when_cli_left_default():
    env = _env("burst", 1, 1)
    locustfile.apply_profile_load(env)
    assert env.parsed_options.num_users == PROFILES["burst"]["users"]
    assert env.parsed_options.spawn_rate == PROFILES["burst"]["spawn_rate"]


def test_explicit_cli_load_wins():
    env = _env("burst", 7, 3)
    locustfile.apply_profile_load(env)
    assert (env.parsed_options.num_users, env.parsed_options.spawn_rate) == (7, 3)
