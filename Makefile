# Host tools run from a project venv via `python -m ...`; no global installs assumed.
-include .env

VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
RUN_TIME ?= 60s
LOCUST = $(PY) -m locust -f workload/locustfile.py --headless --run-time $(RUN_TIME) --host $(PULSEOPS_API_URL)

# Host-side defaults (direct to published ports); .env or the shell can override.
HOST_DATABASE_URL ?= postgresql+psycopg://pulseops:pulseops@localhost:5432/pulseops
PULSEOPS_API_URL ?= http://localhost:8000
PROMETHEUS_URL ?= http://localhost:9090
JAEGER_URL ?= http://localhost:16686
GRAFANA_URL ?= http://localhost:3000
TOXIPROXY_URL ?= http://localhost:8474
BCRYPT_ROUNDS ?= 10
SEED_USERS ?= 10000
SEED_PRODUCTS ?= 2000
SEED_ORDERS ?= 300000
export HOST_DATABASE_URL PULSEOPS_API_URL PROMETHEUS_URL JAEGER_URL GRAFANA_URL TOXIPROXY_URL \
	BCRYPT_ROUNDS SEED_USERS SEED_PRODUCTS SEED_ORDERS

.PHONY: up down migrate seed test lint load-normal load-burst scenario diagnose verify report reset

up:
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' and set JWT_SECRET"; exit 1; }
	docker compose up -d --build --wait

down:
	docker compose down

migrate: $(STAMP)
	MIGRATION_DATABASE_URL=$(HOST_DATABASE_URL) $(PY) -m alembic upgrade head

seed: $(STAMP)
	$(PY) -m scripts.seed

TEST_DB_URL ?= postgresql+psycopg://pulseops:pulseops@localhost:5432/pulseops_test

test: $(STAMP)
	docker compose exec -T postgres psql -q -U pulseops -d postgres -c "DROP DATABASE IF EXISTS pulseops_test WITH (FORCE)"
	docker compose exec -T postgres psql -q -U pulseops -d postgres -c "CREATE DATABASE pulseops_test"
	TEST_DATABASE_URL=$(TEST_DB_URL) $(PY) -m pytest -q -rfEs

lint: $(STAMP)
	$(PY) -m ruff check .

load-normal: $(STAMP)
	@mkdir -p reports
	$(LOCUST) --profile normal --csv reports/load-normal

load-burst: $(STAMP)
	@mkdir -p reports
	$(LOCUST) --profile burst --csv reports/load-burst

# usage: make scenario S=S4_missing_index
scenario: $(STAMP)
	@test -n "$(S)" || { echo "usage: make scenario S=<id>  (e.g. S4_missing_index)"; exit 1; }
	$(PY) -m cli run $(S)

diagnose: $(STAMP)
	$(PY) -m cli diagnose

verify: $(STAMP)
	$(PY) -m cli verify

# usage: make report R=<run_id>
report: $(STAMP)
	$(PY) -m cli report $(R)

reset:
	docker compose down -v

# Not a user target: builds the venv and reinstalls when pyproject.toml changes.
$(STAMP): pyproject.toml
	python3 -m venv $(VENV)
	$(PY) -m pip install -q ".[dev,tools]"
	@touch $@
