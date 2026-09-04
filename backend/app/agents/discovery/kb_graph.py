from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.discovery.nodes import (
    heuristic_filter_node,
    init_topic_node,
    prepare_candidate_node,
    route_after_prepare_candidate,
    route_after_save_kb,
    save_kb_article_node,
    search_node,
    summarize_v2_node,
    youtube_embed_node,
)


class KbDiscoveryState(TypedDict, total=False):
    topic: str
    topic_kind: Literal["interest", "stack"]
    tag_id: int | None
    owned_urls: set[str]
    open_slots: int
    candidates: list
    cand_idx: int
    results: list
    article: dict


def build_kb_discovery_graph():
    workflow = StateGraph(dict)

    workflow.add_node("init", init_topic_node)
    workflow.add_node("search", search_node)
    workflow.add_node("filter", heuristic_filter_node)
    workflow.add_node("prepare", prepare_candidate_node)
    workflow.add_node("summarize", summarize_v2_node)
    workflow.add_node("youtube", youtube_embed_node)
    workflow.add_node("save", save_kb_article_node)

    workflow.set_entry_point("init")
    workflow.add_edge("init", "search")
    workflow.add_edge("search", "filter")
    workflow.add_edge("filter", "prepare")
    workflow.add_conditional_edges(
        "prepare",
        route_after_prepare_candidate,
        {"summarize": "summarize", "end": END},
    )
    workflow.add_edge("summarize", "youtube")
    workflow.add_edge("youtube", "save")
    workflow.add_conditional_edges(
        "save",
        route_after_save_kb,
        {"prepare": "prepare", "end": END},
    )

    return workflow.compile()


_kb_discovery_graph = build_kb_discovery_graph()


async def run_kb_discovery_for_topic(
    topic: str,
    topic_kind: Literal["interest", "stack"],
    tag_id: int | None,
):
    initial_state: KbDiscoveryState = {
        "topic": topic,
        "topic_kind": topic_kind,
        "tag_id": tag_id,
    }
    await _kb_discovery_graph.ainvoke(initial_state)
