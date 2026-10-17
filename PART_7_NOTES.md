# PART 7 — Workload

## What was built
- `workload/profiles.py` — `PROFILES` (normal / burst / pool_pressure: `users`, `spawn_rate`, `weights`) and `TASK_ROUTES` (task key -> method + route template). All load numbers live here.
- `workload/locustfile.py` — one `PulseOpsUser(HttpUser)`. `on_start` logs in as `user<N>@example.com` / `loadtest-pass` (N in 1..`SEED_USERS`). A single `@task` picks a handler via `random.choices` with the profile weights (chosen over Locust's own task-weight machinery so the weights can come from a CLI argument). `--profile` is registered through `init_command_line_parser`. Request names are route templates (`/products/{id}`, `/orders`, ...). `POST /orders` uses a fresh `Idempotency-Key` each attempt, 1-3 distinct products; 201 and 409 count as success, anything else (5xx, 404, 422, timeout = status 0) is a failure. `wait_time = between(0.1, 0.5)`, request timeout 10s.
- `tests/p7_workload/` — `test_profiles.py` (names, weights sum to 100, mixes, burst = 3x spawn, route templates match Contract 4.5), `test_locustfile.py` (handler per task, order payload validity, profile applies load unless `-u/-r` given), `test_smoke.py` (15s headless run against `PULSEOPS_API_URL`, asserts requests > 0 and failures < 1%; skipped if unset).

## How it was verified (honest)
- ruff (line length 100) clean; `compileall` clean.
- pytest in a scratch copy with temporary `__init__.py` stubs (not shipped): **11 passed, 2 skipped** with the real environment (the two skips: `locust` not importable, `PULSEOPS_API_URL` unset).
- `test_locustfile.py` (4 tests) was additionally run against a minimal stand-in `locust` module (not real Locust) to check my own logic: passed. This does NOT prove real Locust behaviour.
- **NOT run:** `locust` itself. PyPI was blocked by this session's network policy (403 from the egress proxy) and no Locust wheel was cached. So the headless run, CSV output, the 30s smoke run and **RPS are not measured**. The acceptance criterion (30s smoke, >0 requests, <1% failures) is therefore unverified.

## Verify yourself
```
pip install -e ".[tools,dev]"            # locust, pytest (Part 1 groups)
pytest tests/p7_workload -q
make up && make seed
PULSEOPS_API_URL=http://localhost:8000 pytest tests/p7_workload/test_smoke.py -q
locust -f workload/locustfile.py --headless --profile normal --run-time 30s \
  --csv reports/tmp --host $PULSEOPS_API_URL
```

## Known risks (things I could not confirm without Locust)
1. `sys.path.insert(...)` in the locustfile makes `from workload.profiles import ...` work wherever Locust is started from; assumes `__file__` is set when Locust loads the file.
2. `apply_profile_load` mutates `parsed_options.num_users/spawn_rate` in the `init` event, assuming headless start reads them afterwards. It overrides only when they equal Locust's default (None/1), so an explicit `-u 1` is indistinguishable from the default.
3. Logins use bcrypt (cost 12 unless `BCRYPT_ROUNDS` is lowered) on a 1-CPU API container: the spawn phase will be CPU-heavy, especially `burst`. Baseline numbers taken during spawn will be skewed; the CLI's BASELINE window should start after ramp-up.
4. JWT lifetime is 30 min (`JWT_EXPIRE_MINUTES`); runs longer than that would see 401s.

## Contract concerns
- Contract 4.6 gives the Locust command without `-u/-r`. If risk 2 bites, Part 9 should pass `-u`/`-r` explicitly from `workload.profiles.PROFILES[name]`.
- If Part 1's ruff config enables `E402`, add `# noqa: E402` to the `workload.profiles` import in `locustfile.py` (and the test); with ruff's default rules the directive is reported as unused, so I left it out.

## Dependency requests
None (uses `locust`, `pytest` already in Part 1's `tools`/`dev` groups).
