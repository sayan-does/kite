"""Unit tests for stateless signed access tokens (no DB)."""

from app.services.tokens import mint_token, verify_token


def test_roundtrip():
    uid = "11111111-2222-3333-4444-555555555555"
    token = mint_token(uid)
    assert token.startswith("kite_")
    assert verify_token(token) == uid


def test_deterministic():
    uid = "abc-123"
    assert mint_token(uid) == mint_token(uid)


def test_tampered_signature_rejected():
    token = mint_token("user-x")
    assert verify_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb")) is None


def test_tampered_payload_rejected():
    token = mint_token("user-x")
    prefix, rest = token.split("_", 1)
    uid_part, sig_part = rest.split(".", 1)
    # swap the payload to a different user, keep the old signature
    forged = f"kite_{mint_token('user-y').split('_', 1)[1].split('.', 1)[0]}.{sig_part}"
    assert verify_token(forged) is None


def test_garbage_rejected():
    assert verify_token(None) is None
    assert verify_token("") is None
    assert verify_token("not-a-kite-token") is None
    assert verify_token("kite_onlyonepart") is None
