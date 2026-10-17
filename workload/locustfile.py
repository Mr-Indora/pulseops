"""Locust workload for PulseOps.

locust -f workload/locustfile.py --headless --profile normal --run-time 60s \
    --csv reports/tmp --host $PULSEOPS_API_URL
"""
import os
import random
import sys
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `workload.*`
from workload.profiles import PROFILES, TASK_ROUTES

SEED_USERS = int(os.environ.get("SEED_USERS", "10000"))
SEED_PRODUCTS = int(os.environ.get("SEED_PRODUCTS", "2000"))
PASSWORD = "loadtest-pass"  # documented seed password (Part 2)
TIMEOUT = 10  # seconds per request


def profile_name(opts) -> str:
    # Locust >= 2.4x already owns `--profile` (a free-form label), so we reuse it instead of redefining it.
    name = getattr(opts, "profile", None) or "normal"
    if name not in PROFILES:
        raise SystemExit(f"unknown --profile {name!r}; choose one of {sorted(PROFILES)}")
    return name


@events.init.add_listener
def apply_profile_load(environment, **_):
    # Profile supplies users/spawn rate unless -u/-r were set explicitly (locust default is 1).
    opts = environment.parsed_options
    profile = PROFILES[profile_name(opts)]
    if opts.num_users in (None, 1):
        opts.num_users = profile["users"]
    if opts.spawn_rate in (None, 1):
        opts.spawn_rate = profile["spawn_rate"]


def login_failure(r) -> str:
    """Safe, non-secret reason: status 0 means no HTTP response (timeout / connection error)."""
    if r.status_code == 0:
        return f"login got no response (timeout or connection error: {type(getattr(r, 'error', None)).__name__})"
    try:
        code = r.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        code = "unparseable body"
    return f"login returned HTTP {r.status_code} ({code})"


def order_payload() -> dict:
    # Distinct ids: order_items has PRIMARY KEY (order_id, product_id).
    ids = random.sample(range(1, SEED_PRODUCTS + 1), k=random.randint(1, 3))
    return {"items": [{"product_id": i, "quantity": random.randint(1, 2)} for i in ids]}


class PulseOpsUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        weights = PROFILES[profile_name(self.environment.parsed_options)]["weights"]
        self.task_names, self.task_weights = list(weights), list(weights.values())
        self.headers = {}
        creds = {"email": f"user{random.randint(1, SEED_USERS)}@example.com", "password": PASSWORD}
        with self.client.post("/auth/login", json=creds, name="/auth/login", timeout=TIMEOUT,
                              catch_response=True) as r:
            if r.status_code == 200:
                self.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
            else:  # authenticated tasks will then fail visibly instead of being skipped
                r.failure(login_failure(r))

    @task
    def act(self):
        name = random.choices(self.task_names, self.task_weights)[0]
        getattr(self, f"do_{name}")()

    def _read(self, key: str, path: str):
        self.client.get(path, name=TASK_ROUTES[key][1], headers=self.headers, timeout=TIMEOUT)

    def do_list_products(self):
        self._read("list_products",
                   f"/products?limit=50&offset={random.randint(0, max(0, SEED_PRODUCTS - 50))}")

    def do_get_product(self):
        self._read("get_product", f"/products/{random.randint(1, SEED_PRODUCTS)}")

    def do_list_orders(self):
        self._read("list_orders", "/orders?limit=20")

    def do_top_products(self):
        self._read("top_products", "/stats/top-products?days=30&limit=10")

    def do_create_order(self):
        headers = {**self.headers, "Idempotency-Key": str(uuid.uuid4())}
        with self.client.post("/orders", json=order_payload(), headers=headers,
                              name=TASK_ROUTES["create_order"][1], timeout=TIMEOUT,
                              catch_response=True) as r:
            # 409 insufficient_stock is an expected business outcome; status 0 = timeout/conn error.
            if r.status_code in (201, 409):
                r.success()
            else:
                r.failure(f"unexpected status {r.status_code}")
