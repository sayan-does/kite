"""Stateless signed access tokens for the MCP server + personal RSS feed.

A token embeds the user id and an HMAC over it, so it verifies to a user with
no database lookup — which means these features need no schema migration. The
raw token is what users paste into their AI client (MCP) or RSS reader.

Revocation is global (rotate the secret). A future per-user salt column can make
it per-user; intentionally deferred so this ships without the blocked migration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from app.config import settings

_SECRET = (
    getattr(settings, "INTERNAL_TRIGGER_SECRET", "")
    or settings.SUPABASE_JWT_SECRET
    or "kite-dev-secret"
).encode()
_PREFIX = "kite_"
_SIG_LEN = 24


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint_token(user_id: str) -> str:
    """Deterministic signed token for a user id (same input → same token)."""
    uid = user_id.encode()
    sig = hmac.new(_SECRET, uid, hashlib.sha256).digest()[:_SIG_LEN]
    return f"{_PREFIX}{_b64(uid)}.{_b64(sig)}"


def verify_token(token: str | None) -> str | None:
    """Return the user id if the token is valid and untampered, else None."""
    if not token or not token.startswith(_PREFIX):
        return None
    body = token[len(_PREFIX):]
    try:
        uid_part, sig_part = body.split(".", 1)
        uid = _unb64(uid_part)
        sig = _unb64(sig_part)
    except (ValueError, Exception):
        return None
    expected = hmac.new(_SECRET, uid, hashlib.sha256).digest()[:_SIG_LEN]
    if hmac.compare_digest(sig, expected):
        try:
            return uid.decode()
        except UnicodeDecodeError:
            return None
    return None
