"""Password hashing and JWT helpers. Logs nothing: passwords and tokens must never reach logs."""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

_ALGORITHM = (
    "HS256"  # pinned on decode, so "alg": "none" and algorithm-confusion tokens are rejected
)
_SECRET = os.environ.get("JWT_SECRET", "")
if not _SECRET:
    raise RuntimeError("JWT_SECRET must be set")  # fail at import, not on the first login
_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))
_EXPIRE = timedelta(minutes=int(os.environ.get("JWT_EXPIRE_MINUTES", "30")))


def _b(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes (and bcrypt>=5 raises beyond that).
    return password.encode()[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_b(password), bcrypt.gensalt(rounds=_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_b(password), password_hash.encode())
    except ValueError:  # malformed stored hash: treat as mismatch
        return False


# Same cost as real hashes, so a login for an unknown email takes as long as a wrong password.
DUMMY_HASH = hash_password("dummy-password-for-timing")


def create_token(user_id: int) -> str:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "iat": now, "exp": now + _EXPIRE}
    return jwt.encode(claims, _SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> int:
    """Return the user id. Raises jwt.PyJWTError or ValueError on any invalid token."""
    payload = jwt.decode(
        token, _SECRET, algorithms=[_ALGORITHM], options={"require": ["sub", "exp", "iat"]}
    )
    return int(payload["sub"])
