import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest

from app.auth import router as auth_router
from app.auth.security import DUMMY_HASH, create_token

PASSWORD = "correct-horse-battery"


def new_email() -> str:
    return f"p4-{uuid.uuid4().hex}@example.com"


def register(client, email=None, password=PASSWORD):
    return client.post("/auth/register", json={"email": email or new_email(), "password": password})


def login_token(client, email, password=PASSWORD) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def forged(sub="1", key=None, algorithm="HS256", **overrides) -> str:
    now = datetime.now(UTC)
    claims = {"sub": sub, "iat": now, "exp": now + timedelta(minutes=5), **overrides}
    return jwt.encode(claims, key or os.environ["JWT_SECRET"], algorithm=algorithm)


def assert_unauthorized(r):
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "unauthorized" and "request_id" in err


def test_register_login_and_protected_call(client):
    email = new_email()
    r = register(client, email)
    assert r.status_code == 201
    user_id = r.json()["id"]
    assert r.json() == {"id": user_id, "email": email}  # no password_hash leaks

    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.json()["token_type"] == "bearer"
    token = r.json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"sub", "iat", "exp"} and claims["sub"] == str(user_id)

    r = client.get("/_protected", headers=bearer(token))
    assert r.status_code == 200 and r.json() == {"id": user_id, "email": email}


def test_email_is_normalised_to_lowercase(client):
    email = new_email()
    r = register(client, f"  {email.upper()} ")
    assert r.status_code == 201 and r.json()["email"] == email
    login_token(client, email.upper())


def test_duplicate_email_409_even_with_different_case(client):
    email = new_email()
    assert register(client, email).status_code == 201
    r = register(client, email.upper())
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "a@example.com", "password": "short"},  # < 8 chars
        {"email": "a@example.com", "password": "x" * 73},  # > bcrypt limit
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "a@example.com"},
    ],
)
def test_register_validation_422(client, payload):
    assert client.post("/auth/register", json=payload).status_code == 422


def test_login_failures_are_indistinguishable(client):
    email = new_email()
    register(client, email)
    wrong_pw = client.post("/auth/login", json={"email": email, "password": "wrong-password"})
    unknown = client.post("/auth/login", json={"email": new_email(), "password": PASSWORD})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_unknown_user_still_runs_bcrypt_verify(client, monkeypatch):
    calls = []
    real = auth_router.verify_password
    monkeypatch.setattr(auth_router, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    client.post("/auth/login", json={"email": new_email(), "password": PASSWORD})
    assert calls == [DUMMY_HASH]


def test_login_releases_db_connection_before_bcrypt(client, session_factory, monkeypatch):
    # Regression: login held a pooled connection for the whole bcrypt (pool=5), so concurrent
    # logins hit db_pool_timeout (503) under load.
    email = new_email()
    register(client, email)
    pool = session_factory.kw["bind"].pool
    seen = []
    real = auth_router.verify_password
    monkeypatch.setattr(
        auth_router, "verify_password", lambda p, h: seen.append(pool.checkedout()) or real(p, h)
    )
    assert client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert seen == [0]


def test_missing_or_malformed_authorization_header(client):
    assert_unauthorized(client.get("/_protected"))
    assert_unauthorized(client.get("/_protected", headers={"Authorization": "Basic abc"}))
    assert_unauthorized(client.get("/_protected", headers=bearer("not-a-jwt")))


def test_expired_token(client):
    uid = register(client).json()["id"]
    now = datetime.now(UTC)
    token = forged(sub=str(uid), iat=now - timedelta(minutes=10), exp=now - timedelta(minutes=5))
    assert_unauthorized(client.get("/_protected", headers=bearer(token)))


def test_tampered_token(client):
    email = new_email()
    register(client, email)
    head, payload, sig = login_token(client, email).split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert_unauthorized(client.get("/_protected", headers=bearer(f"{head}.{payload}.{flipped}")))


def test_token_signed_with_other_key_rejected(client):
    uid = register(client).json()["id"]
    token = forged(sub=str(uid), key="some-other-secret-0123456789-0123456789")
    assert_unauthorized(client.get("/_protected", headers=bearer(token)))


def test_alg_none_rejected(client):
    uid = register(client).json()["id"]
    token = jwt.encode({"sub": str(uid), "exp": 9999999999, "iat": 1}, key=None, algorithm="none")
    assert_unauthorized(client.get("/_protected", headers=bearer(token)))


def test_token_missing_required_claim_rejected(client):
    uid = register(client).json()["id"]
    token = jwt.encode({"sub": str(uid), "exp": 9999999999}, os.environ["JWT_SECRET"], "HS256")
    assert_unauthorized(client.get("/_protected", headers=bearer(token)))


def test_valid_token_for_nonexistent_user_rejected(client):
    assert_unauthorized(client.get("/_protected", headers=bearer(create_token(2**62))))


def test_missing_jwt_secret_fails_fast():
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run(
        [sys.executable, "-c", "import app.auth.security"],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode != 0 and "JWT_SECRET" in r.stderr
