"""Encrypt ERP credentials at rest (BUILD_PLAN §9 security baseline; ADR 0006).

ERP keys typed into the Connectors page are stored in `erp_connections.credentials_encrypted`
as one Fernet token (AES-128-CBC + HMAC-SHA256). The master key, ORRFIN_SECRET_KEY, lives
only in `.env` locally (Secrets Manager on AWS), never in the database or the repo, so a
database dump alone reveals no ERP key.

Decrypted values exist only in memory, inside `app.adapters.registry`, for the length of one
ERP call. Nothing here logs, and no error message includes a value.
"""

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretsUnavailable(RuntimeError):
    """The master key is missing or wrong, so stored ERP credentials cannot be used."""


def _fernet() -> Fernet:
    key = get_settings().orrfin_secret_key
    if key is None or not key.get_secret_value():
        raise SecretsUnavailable(
            "ORRFIN_SECRET_KEY is not set in .env. Run scripts/dev.ps1 once (it creates one), then restart.")
    try:
        return Fernet(key.get_secret_value().encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise SecretsUnavailable("ORRFIN_SECRET_KEY is not a valid key (expected 44 url-safe base64 characters).") from exc


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


def encrypt_credentials(values: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(values, sort_keys=True).encode("utf-8")).decode("ascii")


def decrypt_credentials(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode("ascii")))
    except InvalidToken as exc:
        # Usually: ORRFIN_SECRET_KEY changed after the keys were saved. Re-enter them.
        raise SecretsUnavailable("Saved ERP credentials can't be decrypted with the current ORRFIN_SECRET_KEY; "
                                 "enter them again on the Connectors page.") from exc


def describe(values: dict[str, Any], secret_fields: set[str]) -> dict[str, dict[str, Any]]:
    """What the browser may see about saved credentials: set or not, and the last 4 characters of a secret."""
    out: dict[str, dict[str, Any]] = {}
    for name, value in values.items():
        text = str(value or "")
        if name in secret_fields:
            out[name] = {"set": bool(text), "hint": f"…{text[-4:]}" if len(text) >= 12 else ("set" if text else "")}
        else:
            out[name] = {"set": bool(text), "hint": text}
    return out
