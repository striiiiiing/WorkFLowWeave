"""Official LangGraph saver ownership and message-only projection graph."""

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph


class CheckpointStore:
    def __init__(self, path: Path, *, saver=None):
        self.path = path
        self.saver = saver
        self._owner = None
        self.projection = None

    async def initialize(self):
        if self.projection is not None:
            return
        if self.saver is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._owner = AsyncSqliteSaver.from_conn_string(str(self.path))
            self.saver = await self._owner.__aenter__()
            await self.saver.setup()
        builder = StateGraph(MessagesState)
        builder.add_node("projection", lambda state: {})
        builder.set_entry_point("projection")
        builder.add_edge("projection", END)
        self.projection = builder.compile(checkpointer=self.saver)

    async def close(self):
        if self._owner is not None:
            await self._owner.__aexit__(None, None, None)
            self._owner = None
            self.saver = None
            self.projection = None
