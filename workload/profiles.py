"""Workload profiles: the single place where load numbers live."""

# Task key -> (HTTP method, route template). The template is exactly what the API stores in the
# Prometheus `route` label, so Locust stats line up with http_request_duration_seconds.
TASK_ROUTES = {
    "list_products": ("GET", "/products"),
    "get_product": ("GET", "/products/{id}"),
    "list_orders": ("GET", "/orders"),
    "create_order": ("POST", "/orders"),
    "top_products": ("GET", "/stats/top-products"),
}

_MIX = {"list_products": 50, "get_product": 20, "list_orders": 15, "create_order": 10,
        "top_products": 5}

PROFILES = {
    "normal": {"users": 20, "spawn_rate": 5, "weights": dict(_MIX)},
    "burst": {"users": 50, "spawn_rate": 15, "weights": dict(_MIX)},  # 3x normal spawn rate
    "pool_pressure": {
        "users": 40,
        "spawn_rate": 10,
        "weights": {"top_products": 90, "list_products": 5, "get_product": 5},
    },
}
