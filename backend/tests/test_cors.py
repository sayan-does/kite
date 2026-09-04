from fastapi.testclient import TestClient

from app.config import parse_cors_origins, settings
from app.main import app

client = TestClient(app)


def test_parse_cors_origins_default():
    assert parse_cors_origins(None) == ["http://localhost:5173", "http://localhost:4173"]
    assert parse_cors_origins("") == ["http://localhost:5173", "http://localhost:4173"]
    assert parse_cors_origins("   ") == ["http://localhost:5173", "http://localhost:4173"]


def test_parse_cors_origins_csv_strips_trailing_slash():
    assert parse_cors_origins("https://kite.example.com/, https://www.kite.example.com") == [
        "https://kite.example.com",
        "https://www.kite.example.com",
    ]


def test_cors_preflight_allows_configured_origin():
    origin = settings.CORS_ORIGINS[0]
    resp = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_preflight_rejects_unknown_origin():
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"
