"""LangGraph fast collection with Send fan-out."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.collectors.base import CollectedItem
from app.config import settings
from app.db import supabase
from app.services.feed_pipeline import _collect_one_feed, _update_feed_poll


class CollectState(TypedDict, total=False):
    feed_ids: list[str]
    topics: list[str]
    items: Annotated[list, operator.add]


async def _collect_feed_node(state: dict) -> dict:
    feed_id = state["feed_id"]
    row = supabase.table("source_feeds").select("*").eq("id", feed_id).execute()
    if not row.data:
        return {"items": []}
    feed = row.data[0]
    items, poll = await _collect_one_feed(feed)
    _update_feed_poll(feed_id, poll)
    return {"items": items}


def _fan_out(state: CollectState):
    return [Send("_collect_feed_node", {"feed_id": fid}) for fid in state.get("feed_ids", [])]


def build_collect_graph():
    g = StateGraph(CollectState)
    g.add_node("_collect_feed_node", _collect_feed_node)
    g.add_conditional_edges(START, _fan_out)
    g.add_edge("_collect_feed_node", END)
    return g.compile()


_collect_graph = build_collect_graph()


async def collect_feeds_parallel(feed_ids: list[str]) -> list[CollectedItem]:
    if not feed_ids:
        return []
    result = await _collect_graph.ainvoke({"feed_ids": feed_ids[: settings.COLLECT_MAX_CONCURRENCY]})
    return result.get("items", [])
