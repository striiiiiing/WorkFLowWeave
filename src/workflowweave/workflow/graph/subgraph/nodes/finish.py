from workflowweave.workflow.graph.subgraph.nodes.state import phase


def finish(state):
    status = (
        "failed"
        if state["status"] == "failed"
        else "partial"
        if state.get("degraded")
        else "completed"
    )
    return phase(
        state,
        "finish",
        status=status,
        stopped=state.get("stopped", False),
        error=state.get("error"),
    )
