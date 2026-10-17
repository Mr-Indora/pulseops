# PART 1 — Foundation notes

## What was built
Dockerfile, docker-compose.yml, Makefile, pyproject.toml, .env.example, .gitignore, .dockerignore,
and empty `__init__.py` in: app, app/{core,api,db,auth,obs,reliability}, faults, cli, workload,
scripts, tests, tests/{p2_db,p3_api,p4_auth,p5_obs,p7_workload,p8_faults,p9_cli,e2e}.
No `.gitkeep` files: every directory this part creates holds an `__init__.py`, and `reports/` is
gitignored and created by `make load-*`.

## Verified (sandbox had no Docker and no network)
- pyproject.toml parses (tomllib); docker-compose.yml parses (PyYAML) and has the 7 services.
- Container name, cpus, restart, grace period and published ports checked against Contract 4.2 by script.
- `make -n` dry-runs for up / migrate / scenario (incl. the missing-S guard).
- Image tags checked against public pages: toxiproxy 2.9.0, jaeger all-in-one 1.62.0, postgres-exporter v0.15.0.

## NOT verified
- `docker compose config`, `docker build`, `make up` were not run. Tags postgres:16.4,
  prom/prometheus:v2.53.0, grafana/grafana:11.1.0 are from my own knowledge, not checked.
- Toxiproxy healthcheck runs `/toxiproxy-cli list` (image is scratch, no shell/curl). Path is from the
  image layout of older releases; confirm on first `make up`.
- Memory caps (sum 3.0 GB) are caps, not measurements.

## How others must use it
- `docker compose config` needs JWT_SECRET (compose uses `:?`): run `cp .env.example .env` first, or
  `docker compose --env-file .env.example config`. CI (P10) must do the same.
- Prometheus gets `./deploy/observability/prometheus` at `/etc/prometheus` (prometheus.yml, alerts.yml).
- Grafana gets provisioning at `/etc/grafana/provisioning` and dashboards at `/var/lib/grafana/dashboards`;
  the P6 dashboard provider `path` must be `/var/lib/grafana/dashboards`.
- Image runs `alembic upgrade head` using MIGRATION_DATABASE_URL: P2's `migrations/env.py` must read it.
  Host `make migrate` sets it to HOST_DATABASE_URL.
- `make seed` runs `python -m scripts.seed`, so P2's seed needs a `__main__` guard and must use HOST_DATABASE_URL.
- `make report R=<run_id>` forwards R to `python -m cli report`.
- Not exported by the Makefile: JWT_SECRET (tests set their own).

## Contract concerns
- Every API container start re-runs `alembic upgrade head`, so a restart during S4 (or S6) silently
  re-creates `ix_orders_user_created` and ends the scenario. Do not restart the API mid-S4.
- P4 mentions a BCRYPT_ROUNDS override, which is not in Contract 4.3, so compose does not pass it.
- Dockerfile spec says "copy app/migrations/alembic.ini"; I followed the tree in 4.1 (`app/`, `migrations/`, `alembic.ini`).
- The API container has an extra healthcheck (`/health/live`) so `docker compose up --wait` works. Not in the Contract.
- Makefile has one non-user file target, `.venv/.installed`, which builds the venv.

## Dependency requests
None. Possible gap for P3: if schemas use `EmailStr`, `email-validator` is not in the dependency list.
