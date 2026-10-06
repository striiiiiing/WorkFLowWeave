from workflowweave.workflow.graph.subgraph.nodes.state import phase


def arrange(state):
    degraded = state.get("degraded", False) or any(
        i["status"] in {"failed", "timeout"} for i in state.get("deliveries", {}).values()
    )
    return phase(state, "notify", degraded=degraded)
