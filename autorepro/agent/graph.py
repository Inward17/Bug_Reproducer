"""LangGraph state machine definition — nodes, edges, and conditional routing."""

from langgraph.graph import StateGraph, END

from agent.state import AgentState, FailureType
from agent.nodes.analyze  import analyze_node
from agent.nodes.inspect  import inspect_node
from agent.nodes.generate import generate_node
from agent.nodes.execute  import execute_node
from agent.nodes.evaluate import evaluate_node
from agent.nodes.refine   import refine_node


def route_after_evaluate(state: AgentState) -> str:
    """Route after evaluation: end on success, refine if attempts remain, else end failure."""
    if state["success"]:
        return "end_success"

    if state.get("bug_absent"):
        # Refine already concluded, from the full history, that the bug is not present.
        return "end_failure"

    if state["attempt_count"] < state["max_attempts"]:
        # Every failure mode is worth refining, including "the script ran but saw no bug"
        # (FailureType.BUG_NOT_OBSERVED) — that is usually a wrong verification condition,
        # which is exactly what the refine prompt is written to diagnose.
        return "refine"
    return "end_failure"


def route_after_refine(state: AgentState) -> str:
    """Stop early when refine concluded the bug does not exist; otherwise retry."""
    return "end_absent" if state.get("bug_absent") else "execute"


graph = StateGraph(AgentState)
graph.add_node("analyze",  analyze_node)
graph.add_node("inspect",  inspect_node)
graph.add_node("generate", generate_node)
graph.add_node("execute",  execute_node)
graph.add_node("evaluate", evaluate_node)
graph.add_node("refine",   refine_node)
graph.set_entry_point("analyze")
graph.add_edge("analyze",  "inspect")
graph.add_edge("inspect",  "generate")
graph.add_edge("generate", "execute")
graph.add_edge("execute",  "evaluate")
graph.add_conditional_edges("evaluate", route_after_evaluate, {
    "end_success": END,
    "refine":      "refine",
    "end_failure": END,
})
graph.add_conditional_edges("refine", route_after_refine, {
    "execute":    "execute",
    "end_absent": END,
})

compiled = graph.compile()

__all__ = ["compiled", "graph", "route_after_evaluate", "route_after_refine", "FailureType"]
