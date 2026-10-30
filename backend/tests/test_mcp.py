"""Tests for the Kite MCP server (JSON-RPC over POST /mcp)."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import mcp_server
from app.services.tokens import mint_token

client = TestClient(app)


@pytest.fixture(scope="module")
def test_user():
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    h = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    email = f"mcp-{uuid.uuid4().hex[:8]}@example.com"
    pw = uuid.uuid4().hex
    r = httpx.post(url, headers=h, json={"email": email, "password": pw, "email_confirm": True})
    r.raise_for_status()
    uid = r.json()["id"]
    yield {"id": uid}
    try:
        httpx.delete(f"{url}/{uid}", headers=h)
    except Exception:
        pass


def _rpc(method, rpc_id=1, params=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers)


def test_mcp_requires_token():
    assert _rpc("tools/list").status_code == 401
    assert _rpc("tools/list", token="bogus").status_code == 401


def test_initialize_handshake(test_user):
    token = mint_token(test_user["id"])
    resp = _rpc("initialize", token=token)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["serverInfo"]["name"] == "kite"
    assert "protocolVersion" in result


def test_tools_list(test_user):
    token = mint_token(test_user["id"])
    resp = _rpc("tools/list", token=token)
    names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert names == {"get_feed", "dependency_risk", "whats_new", "search_tech"}


def test_initialized_notification_returns_202(test_user):
    token = mint_token(test_user["id"])
    resp = _rpc("notifications/initialized", rpc_id=None, token=token)
    assert resp.status_code == 202


def test_unknown_method_errors(test_user):
    token = mint_token(test_user["id"])
    resp = _rpc("no/such", token=token)
    assert resp.json()["error"]["code"] == -32601


def test_tools_call_dispatches(monkeypatch, test_user):
    async def fake_call_tool(name, args, user_id):
        assert name == "search_tech"
        assert user_id == test_user["id"]
        return '{"query": "rust", "results": []}'

    monkeypatch.setattr(mcp_server, "call_tool", fake_call_tool)
    token = mint_token(test_user["id"])
    resp = _rpc("tools/call", params={"name": "search_tech", "arguments": {"query": "rust"}}, token=token)
    assert resp.status_code == 200
    content = resp.json()["result"]["content"]
    assert content[0]["type"] == "text"
    assert "rust" in content[0]["text"]


@pytest.mark.asyncio
async def test_call_tool_unknown_raises():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        await mcp_server.call_tool("nope", {}, "uid")
