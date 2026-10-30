"""Kite MCP server — Streamable-HTTP transport (JSON-RPC over POST).

Point an MCP client (Claude Desktop/Code) at POST /mcp with your personal Kite
token (Authorization: Bearer <token>, X-Kite-Token, or ?token=). Tool logic and
protocol handling live in app.services.mcp_server.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.services.mcp_server import TOOLS, handle_rpc
from app.services.tokens import verify_token

router = APIRouter()


def _extract_token(request: Request, query_token: str | None) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-kite-token") or query_token


@router.get("/mcp")
async def mcp_discovery():
    """Lightweight discovery (not part of MCP) so humans can see the tools."""
    return {
        "server": "kite",
        "transport": "streamable-http (POST /mcp, JSON-RPC 2.0)",
        "auth": "Authorization: Bearer <your Kite token from /me/token>",
        "tools": [t["name"] for t in TOOLS],
    }


@router.post("/mcp")
async def mcp_endpoint(request: Request, token: str | None = Query(None)):
    user_id = verify_token(_extract_token(request, token))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or missing Kite token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Support a JSON-RPC batch as well as a single request.
    if isinstance(payload, list):
        responses = [r for r in [await handle_rpc(p, user_id) for p in payload] if r is not None]
        return JSONResponse(responses) if responses else Response(status_code=202)

    response = await handle_rpc(payload, user_id)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response)
