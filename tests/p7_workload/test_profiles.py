import pytest

from workload.profiles import PROFILES, TASK_ROUTES

# Route templates from Contract 4.5; must match the Prometheus `route` label.
CONTRACT_ROUTES = {"/products", "/products/{id}", "/orders", "/stats/top-products"}
NORMAL_MIX = {"list_products": 50, "get_product": 20, "list_orders": 15, "create_order": 10,
              "top_products": 5}


def test_profile_names():
    assert set(PROFILES) == {"normal", "burst", "pool_pressure"}


@pytest.mark.parametrize("name", PROFILES)
def test_weights_sum_to_100_and_use_known_tasks(name):
    weights = PROFILES[name]["weights"]
    assert sum(weights.values()) == 100
    assert set(weights) <= set(TASK_ROUTES)


@pytest.mark.parametrize("name", PROFILES)
def test_load_numbers_positive(name):
    assert PROFILES[name]["users"] > 0
    assert PROFILES[name]["spawn_rate"] > 0


def test_normal_profile():
    assert PROFILES["normal"]["users"] == 20
    assert PROFILES["normal"]["weights"] == NORMAL_MIX


def test_burst_is_same_mix_with_3x_spawn_rate():
    assert PROFILES["burst"]["users"] == 50
    assert PROFILES["burst"]["weights"] == NORMAL_MIX
    assert PROFILES["burst"]["spawn_rate"] == 3 * PROFILES["normal"]["spawn_rate"]


def test_pool_pressure_is_mostly_stats():
    p = PROFILES["pool_pressure"]
    assert p["users"] == 40
    assert p["weights"]["top_products"] == 90


def test_request_names_are_route_templates():
    assert {route for _, route in TASK_ROUTES.values()} == CONTRACT_ROUTES
