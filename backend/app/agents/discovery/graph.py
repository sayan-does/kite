from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.discovery.interest_resolver import WeightedInterest
from app.agents.discovery.nodes import (
    citation_extract_node,
    filter_relevance_node,
    heuristic_filter_node,
    init_node,
    route_after_filter,
    route_after_init,
    route_after_save,
    save_article_node,
    save_article_v2_node,
    search_node,
    select_next_interest_node,
    summarize_node,
    summarize_v2_node,
    youtube_embed_node,
)


def build_discovery_graph() -> StateGraph:
    workflow = StateGraph(dict)

    workflow.add_node("search", search_node)
    workflow.add_node("filter", filter_relevance_node)
    workflow.add_node("summarize", summarize_node)
    workflow.add_node("citations", citation_extract_node)
    workflow.add_node("youtube", youtube_embed_node)
    workflow.add_node("save", save_article_node)

    workflow.set_entry_point("search")
    workflow.add_edge("search", "filter")
    workflow.add_edge("filter", "summarize")
    workflow.add_edge("summarize", "citations")
    workflow.add_edge("citations", "youtube")
    workflow.add_edge("youtube", "save")

    return workflow.compile()


class DiscoveryState(TypedDict, total=False):
    user_id: str
    ranked_interests: list[WeightedInterest]
    interest_idx: int
    open_slots: int
    articles_saved: int
    current_candidates: list
    topic: str
    source: str
    tag: str
    tag_id: int
    results: list
    article: dict
    exhausted: bool


def build_discovery_v2_graph():
    workflow = StateGraph(dict)

    workflow.add_node("init", init_node)
    workflow.add_node("select", select_next_interest_node)
    workflow.add_node("search", search_node)
    workflow.add_node("filter", heuristic_filter_node)
    workflow.add_node("summarize", summarize_v2_node)
    workflow.add_node("youtube", youtube_embed_node)
    workflow.add_node("save", save_article_v2_node)

    workflow.set_entry_point("init")
    workflow.add_conditional_edges("init", route_after_init, {"select": "select", "end": END})
    workflow.add_edge("select", "search")
    workflow.add_edge("search", "filter")
    workflow.add_conditional_edges("filter", route_after_filter, {"summarize": "summarize", "select": "select"})
    workflow.add_edge("summarize", "youtube")
    workflow.add_edge("youtube", "save")
    workflow.add_conditional_edges("save", route_after_save, {"select": "select", "end": END})

    return workflow.compile()


_discovery_graph = build_discovery_graph()
_discovery_v2_graph = build_discovery_v2_graph()


async def run_discovery_for_tag(tag_id: int, tag_name: str):
    initial_state = {"tag": tag_name, "tag_id": tag_id}
    await _discovery_graph.ainvoke(initial_state)


async def run_discovery_for_user(user_id: str):
    initial_state: DiscoveryState = {"user_id": user_id}
    await _discovery_v2_graph.ainvoke(initial_state)
