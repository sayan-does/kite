"""Kite MCP server — JSON-RPC 2.0 core (transport-agnostic).

Users add Kite to their own AI client (Claude Desktop/Code) like a plugin,
authenticating with their personal Kite token. Implemented directly against the
MCP JSON-RPC methods (initialize / tools.list / tools.call) so it needs no extra
SDK dependency and is unit-testable. Tool logic reuses existing Kite services.
"""

from __future__ import annotations

import json

PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict] = [
    {
        "name": "get_feed",
        "description": "Get the user's current Kite tech feed (top articles).",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}},
        },
    },
    {
        "name": "dependency_risk",
        "description": "Summarize risk across the user's tracked dependency stack (security / breaking / outdated).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "whats_new",
        "description": "Recent updates for a package.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "ecosystem": {"type": "string", "enum": ["npm", "pip", "maven"]},
            },
            "required": ["package"],
        },
    },
    {
        "name": "search_tech",
        "description": "Search Kite's collected tech articles by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
            },
            "required": ["query"],
        },
    },
]


async def call_tool(name: str, args: dict, user_id: str) -> str:
    """Dispatch a tool call; returns a text payload (JSON-encoded data)."""
    if name == "get_feed":
        from app.routers.feed import _disabled_citation_types, _kb_feed_page

        limit = int(args.get("limit") or 10)
        page = _kb_feed_page(user_id, None, 1, _disabled_citation_types(user_id), include_body=False)
        items = [
            {"title": a.get("title"), "url": a.get("url"), "summary": a.get("one_liner") or a.get("summary")}
            for a in page["articles"][:limit]
        ]
        return json.dumps({"articles": items}, ensure_ascii=False)

    if name == "dependency_risk":
        from app.db import supabase
        from app.routers.stack import _build_digest_item, _disabled_citation_types, summarize_risk

        deps = (
            supabase.table("tracked_dependencies")
            .select("id, project_name, ecosystem, package_name, version")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        if not deps:
            return json.dumps({"total": 0, "risk_level": "none", "at_risk": []})
        disabled = _disabled_citation_types(user_id)
        items = [_build_digest_item(d, disabled) for d in deps]
        return json.dumps(summarize_risk(items), ensure_ascii=False)

    if name == "whats_new":
        from app.db import supabase

        package = (args.get("package") or "").strip()
        if not package:
            raise ValueError("package is required")
        query = (
            supabase.table("dependency_updates")
            .select("package_name, ecosystem, version, update_type, summary, published_at")
            .eq("package_name", package)
        )
        if args.get("ecosystem"):
            query = query.eq("ecosystem", args["ecosystem"])
        rows = query.order("published_at", desc=True).limit(10).execute().data or []
        return json.dumps({"package": package, "updates": rows}, ensure_ascii=False, default=str)

    if name == "search_tech":
        from app.db import supabase

        q = (args.get("query") or "").strip()
        if not q:
            raise ValueError("query is required")
        limit = int(args.get("limit") or 10)
        rows = (
            supabase.table("kb_articles")
            .select("title, url, one_liner, topic")
            .eq("status", "active")
            .ilike("title", f"%{q}%")
            .limit(limit)
            .execute()
            .data
            or []
        )
        return json.dumps({"query": q, "results": rows}, ensure_ascii=False, default=str)

    raise ValueError(f"Unknown tool: {name}")


def _result(rpc_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _error(rpc_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def handle_rpc(payload: dict, user_id: str) -> dict | None:
    """Handle one JSON-RPC request. Returns None for notifications (no reply)."""
    method = payload.get("method")
    rpc_id = payload.get("id")

    if method == "initialize":
        return _result(rpc_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "kite", "version": "1.0.0"},
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(rpc_id, {})
    if method == "tools/list":
        return _result(rpc_id, {"tools": TOOLS})
    if method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            text = await call_tool(name, args, user_id)
        except Exception as exc:  # surface as an MCP tool error, not a transport error
            return _result(rpc_id, {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True})
        return _result(rpc_id, {"content": [{"type": "text", "text": text}]})

    return _error(rpc_id, -32601, f"Method not found: {method}")
