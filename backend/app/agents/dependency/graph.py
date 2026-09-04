from langgraph.graph import StateGraph

from app.agents.dependency.nodes import (
    changelog_fetch_node,
    conditional_buzz_node,
    dep_summarize_node,
    registry_check_node,
    save_update_node,
    vuln_check_node,
)


def build_dependency_graph() -> StateGraph:
    workflow = StateGraph(dict)

    workflow.add_node("registry_check", registry_check_node)
    workflow.add_node("vuln_check", vuln_check_node)
    workflow.add_node("changelog_fetch", changelog_fetch_node)
    workflow.add_node("conditional_buzz", conditional_buzz_node)
    workflow.add_node("summarize", dep_summarize_node)
    workflow.add_node("save", save_update_node)

    workflow.set_entry_point("registry_check")
    workflow.add_edge("registry_check", "vuln_check")
    workflow.add_edge("vuln_check", "changelog_fetch")
    workflow.add_edge("changelog_fetch", "conditional_buzz")
    workflow.add_edge("conditional_buzz", "summarize")
    workflow.add_edge("summarize", "save")

    return workflow.compile()


_dependency_graph = build_dependency_graph()


async def run_dependency_update(ecosystem: str, package_name: str):
    initial_state = {"ecosystem": ecosystem, "package_name": package_name, "findings": []}
    await _dependency_graph.ainvoke(initial_state)
