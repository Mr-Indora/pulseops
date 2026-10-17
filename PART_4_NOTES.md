# PART 4 — Auth: notes

## What was built
- `app/auth/security.py`: bcrypt `hash_password` / `verify_password` (cost 12, `BCRYPT_ROUNDS` override),
  `DUMMY_HASH`, `create_token(user_id)` / `decode_token(token) -> user_id` (PyJWT, HS256, claims `sub, iat, exp`,
  expiry `JWT_EXPIRE_MINUTES`, default 30). Import raises `RuntimeError` if `JWT_SECRET` is unset or empty.
- `app/auth/router.py`: `POST /auth/register` (201 `{id,email}`, 409 `email_taken`, 422) and
  `POST /auth/login` (200 `{access_token, token_type:"bearer"}`, generic 401 `invalid_credentials`).
- `app/auth/deps.py`: `get_current_user` (`HTTPBearer(auto_error=False)`, so a missing header also gets the
  Contract error body). 401 `unauthorized` for missing / malformed / expired / tampered tokens and for a valid
  token whose user no longer exists.
- `tests/p4_auth/`: `conftest.py` + `test_auth.py` (14 test functions, 17 cases) against real Postgres.
- Size: 106 non-blank, non-comment lines in `app/auth/` (budget ~120).

## Verification: READ THIS
**The pytest suite was NOT run.** The sandbox's egress proxy answers 403 for `pypi.org`, so `fastapi`,
`sqlalchemy`, `psycopg`, `bcrypt`, `httpx` and `pytest` could not be installed. I did not work around the block.
What WAS checked:
- `ruff check` + `ruff format --check` (line length 100): clean, with one caveat. In the sandbox `app.db.models` etc.
  don't exist, so ruff misclassifies function-local imports in `conftest.py`; the import order there is the
  conventional third-party-then-`app.*` one. Re-run `make lint` in the merged repo.
- `py_compile` on all five Python files: OK.
- A throwaway script (not shipped) ran the real `security.py` with a fake `bcrypt` module: round trip,
  30-minute lifetime, expired / tampered-signature / `alg=none` / HS512 / missing-`iat` / non-numeric-`sub` /
  garbage tokens all rejected, and a 100-char password doesn't crash hashing.
- The same script ran the real pydantic rules from `router.py`: email trimmed + lowercased, 7-char and 73-char
  passwords rejected, bad email rejected, missing field rejected.
- NOT verified: real bcrypt behaviour, anything touching FastAPI wiring or the DB (unique-constraint 409,
  login/protected-call flow), and the test suite itself. Expect to fix small things on first run.

Run (needs Postgres; tests skip without `TEST_DATABASE_URL`):
```
export TEST_DATABASE_URL=postgresql+psycopg://pulseops:pulseops@localhost:5432/pulseops
python -m pytest tests/p4_auth -q     # JWT_SECRET / BCRYPT_ROUNDS are set by conftest if absent
ruff check app/auth tests/p4_auth
```
The tests only create the `users` table if missing (`checkfirst`), never drop or truncate, and use unique emails.

## Security checklist
| Item | Result |
|------|--------|
| No secrets in code | PASS. `JWT_SECRET` comes only from the environment. The only literal secret is the test-only value in `tests/p4_auth/conftest.py` (`setdefault`, so a real env value wins). |
| No password in logs | PASS for `app/auth/`: no `logging`/`print` (grep-checked). **Caveat:** FastAPI's default 422 body echoes the rejected `input`, i.e. a too-short password goes back in the response. P3's validation handler and P5's logging must not log request bodies or 422 details. |
| No JWT in logs | PASS for `app/auth/` (same grep). Same caveat for P5: never log the `Authorization` header. |
| Algorithm pinned on decode | PASS. `algorithms=["HS256"]` plus `require: [sub, exp, iat]`. Tests cover `alg=none`; the scratch script also covered HS512. |
| No user enumeration on login | Wrong password and unknown email return an identical body; an unknown email still runs one bcrypt verify against `DUMMY_HASH`. A test asserts that call. Timing equality itself is **not measured**. |
| Hash cost caveat | Verify cost is read from each stored hash, so `BCRYPT_ROUNDS` only changes new hashes and the dummy hash. Seeded users (P2) keep whatever cost P2 used, so `BCRYPT_ROUNDS` won't speed up Locust logins. Timing parity holds only when stored hashes use the same cost as `BCRYPT_ROUNDS`. |

## Contract concerns
- `POST /auth/register` returning 409 reveals which emails exist. The Contract requires it; no rate limiting or
  lockout exists anywhere in the system.
- The Contract gives no error code for login failures; I used `invalid_credentials`. Other 401s use `unauthorized`.
- I assume `AppError(code, message, status)` has attributes with those same names. The test handler in
  `conftest.py` reads `exc.code`, `exc.message`, `exc.status`; the app code only constructs it with keywords.
- `JWT_SECRET` is checked at import, so anything importing `app.main` (P3/P10 tests, CI) must set it.
- bcrypt hashes only the first 72 bytes; passwords are capped at 72 characters and hashing truncates at 72 bytes
  so multi-byte input can't raise (bcrypt>=5 raises on longer input).

## Dependency requests
None. Uses `pyjwt`, `bcrypt`, `pydantic`, `sqlalchemy`, `fastapi` (all in P1's runtime list); tests also need
`httpx` (TestClient) and `pytest`. No `email-validator`: email shape is a simple regex.
