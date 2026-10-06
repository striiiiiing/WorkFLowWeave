"""Checkpointed LangGraph state for an Agent conversation."""

from langgraph.graph import MessagesState


class AgentState(MessagesState, total=False):
    """Durable conversation state plus the identity of its latest turn."""

    turn_id: str
    branch_id: str
