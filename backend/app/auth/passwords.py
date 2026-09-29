"""Password hashing with argon2id (BUILD_PLAN §3 Auth)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# Verified when the email is unknown, so a wrong email takes as long as a wrong password
# and response time doesn't reveal which emails have accounts.
_DUMMY_HASH = _hasher.hash("orrfin-timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False
