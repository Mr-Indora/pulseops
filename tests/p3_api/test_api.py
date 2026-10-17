import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


def _order(pid: int, qty: int = 1) -> dict:
    return {"items": [{"product_id": pid, "quantity": qty}]}


def test_products_list_get_and_404(api, make_product):
    pid = make_product(stock=3, price=999)
    got = api.get(f"/products/{pid}")
    assert got.status_code == 200
    assert got.json()["price_cents"] == 999 and got.json()["stock"] == 3
    assert api.get("/products", params={"limit": 2}).status_code == 200
    assert len(api.get("/products", params={"limit": 2}).json()) <= 2
    missing = api.get("/products/999999999")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "product_not_found"
    assert api.get("/products", params={"limit": 101}).status_code == 422
    assert api.get("/products", params={"limit": 0}).status_code == 422


def test_create_order_happy_path_and_fetch(api, make_user, make_product):
    h, pid = make_user(), make_product(stock=10, price=250)
    r = api.post("/orders", json=_order(pid, 3), headers=h)
    assert r.status_code == 201
    order = r.json()
    assert order["total_cents"] == 750 and order["status"] == "pending"
    assert order["items"] == [{"product_id": pid, "quantity": 3, "unit_price_cents": 250}]
    assert api.get(f"/products/{pid}").json()["stock"] == 7
    assert api.get(f"/orders/{order['id']}", headers=h).json() == order


def test_orders_require_auth(api):
    r = api.post("/orders", json=_order(1))
    assert r.status_code == 401 and "code" in r.json()["error"]
    assert api.get("/orders").status_code == 401


def test_insufficient_stock_is_409_and_atomic(api, make_user, make_product):
    h = make_user()
    plenty, scarce = make_product(stock=10), make_product(stock=2)
    body = {"items": [{"product_id": plenty, "quantity": 1}, {"product_id": scarce, "quantity": 3}]}
    r = api.post("/orders", json=body, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"
    # Whole transaction rolled back: the item that *was* available is untouched.
    assert api.get(f"/products/{plenty}").json()["stock"] == 10
    assert api.get(f"/products/{scarce}").json()["stock"] == 2
    assert api.get("/orders", headers=h).json() == []


def test_unknown_product_is_404(api, make_user):
    r = api.post("/orders", json=_order(999999999), headers=make_user())
    assert r.status_code == 404 and r.json()["error"]["code"] == "product_not_found"


def test_order_validation(api, make_user, make_product):
    h, pid = make_user(), make_product()
    item = {"product_id": pid, "quantity": 1}
    for bad in (
        {"items": []},
        {"items": [item] * 2},                                  # duplicate product
        {"items": [{**item, "product_id": pid + i} for i in range(21)]},  # more than 20
        {"items": [{**item, "quantity": 0}]},
        {"items": [{**item, "quantity": -1}]},
        {"items": [item], "extra": 1},
    ):
        assert api.post("/orders", json=bad, headers=h).status_code == 422


def test_concurrent_orders_never_oversell(api, make_user, make_product):
    from app.main import app

    h, pid = make_user(), make_product(stock=4)

    def buy(_: int) -> int:
        # One client per thread: TestClient is not guaranteed safe to share across threads.
        return TestClient(app).post("/orders", json=_order(pid), headers=h).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(buy, range(10)))
    assert set(codes) <= {201, 409}, codes  # anything else (e.g. 503) is a real failure
    assert codes.count(201) == 4
    assert api.get(f"/products/{pid}").json()["stock"] == 0
    assert len(api.get("/orders", headers=h).json()) == 4


def test_idempotency_key_replay_returns_same_order(api, make_user, make_product):
    h, pid = make_user(), make_product(stock=10)
    headers = {**h, "Idempotency-Key": f"k-{uuid.uuid4().hex}"}
    first = api.post("/orders", json=_order(pid, 2), headers=headers)
    second = api.post("/orders", json=_order(pid, 2), headers=headers)
    assert first.status_code == 201 and second.json() == first.json()
    assert api.get(f"/products/{pid}").json()["stock"] == 8  # decremented once
    assert len(api.get("/orders", headers=h).json()) == 1


def test_idempotency_key_is_scoped_per_user(api, make_user, make_product):
    pid, key = make_product(stock=10), f"k-{uuid.uuid4().hex}"
    a = api.post("/orders", json=_order(pid), headers={**make_user(), "Idempotency-Key": key})
    b = api.post("/orders", json=_order(pid), headers={**make_user(), "Idempotency-Key": key})
    assert a.status_code == b.status_code == 201 and a.json()["id"] != b.json()["id"]


def test_concurrent_same_key_creates_one_order(api, make_user, make_product):
    from app.main import app

    h, pid = make_user(), make_product(stock=10)
    headers = {**h, "Idempotency-Key": f"k-{uuid.uuid4().hex}"}

    def buy(_: int):
        return TestClient(app).post("/orders", json=_order(pid), headers=headers)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(buy, range(6)))
    assert {r.status_code for r in results} == {201}
    assert len({r.json()["id"] for r in results}) == 1
    assert api.get(f"/products/{pid}").json()["stock"] == 9


def test_ownership_isolation(api, make_user, make_product):
    alice, bob, pid = make_user(), make_user(), make_product()
    order_id = api.post("/orders", json=_order(pid), headers=alice).json()["id"]
    assert api.get(f"/orders/{order_id}", headers=alice).status_code == 200
    r = api.get(f"/orders/{order_id}", headers=bob)
    assert r.status_code == 404 and r.json()["error"]["code"] == "order_not_found"
    assert api.get("/orders", headers=bob).json() == []


def test_keyset_pagination(api, make_user, make_product):
    h, pid = make_user(), make_product(stock=100)
    ids = [api.post("/orders", json=_order(pid), headers=h).json()["id"] for _ in range(5)]
    seen, before = [], None
    while True:
        params = {"limit": 2, **({"before": before} if before else {})}
        page = api.get("/orders", params=params, headers=h).json()
        if not page:
            break
        seen += [o["id"] for o in page]
        before = page[-1]["created_at"]
    assert seen == ids[::-1]  # newest first, no gaps, no repeats
    assert api.get("/orders", params={"limit": 101}, headers=h).status_code == 422


def test_top_products(api, make_user, make_product):
    h, pid = make_user(), make_product(stock=100)
    api.post("/orders", json=_order(pid, 7), headers=h)
    r = api.get("/stats/top-products", params={"days": 1, "limit": 100})
    assert r.status_code == 200
    mine = [p for p in r.json() if p["product_id"] == pid]
    assert mine and mine[0]["total_quantity"] == 7
    quantities = [p["total_quantity"] for p in r.json()]
    assert quantities == sorted(quantities, reverse=True)
    assert api.get("/stats/top-products", params={"limit": 101}).status_code == 422


def test_health_live_and_ready(api):
    assert api.get("/health/live").json() == {"status": "ok"}
    assert api.get("/health/ready").json() == {"status": "ok"}


def test_ready_is_503_when_db_unreachable(api, dead_db):
    r = api.get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "reason": "db"}


def test_db_down_maps_to_503_error_body(api, dead_db):
    r = api.get("/products")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "db_unavailable"
    assert "request_id" in r.json()["error"]
