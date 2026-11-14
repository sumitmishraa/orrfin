"""Time-based one-time codes for two-step sign-in (RFC 6238; BUILD_PLAN §9 "Stronger sign-in", change 50).

Standard 6-digit, 30-second TOTP over HMAC-SHA1, which every authenticator app reads from an
`otpauth://` link. The secret is stored encrypted (security/secrets.py). A code is accepted for the
current 30-second step or one step either side (clock drift), and never twice: the last step used is
remembered, so a code seen over someone's shoulder cannot be replayed.
"""

import base64
import hmac
import secrets
import struct
import time
from hashlib import sha1
from urllib.parse import quote

DIGITS = 6
STEP_SECONDS = 30
DRIFT_STEPS = 1


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(secret: str, code: str, *, last_step: int | None, now: float | None = None) -> int | None:
    """The step the code belongs to, or None. A step at or before `last_step` is refused (no replay)."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if (last_step is None or candidate > last_step) and hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def otpauth_uri(secret: str, email: str, issuer: str = "Orrfin") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")
