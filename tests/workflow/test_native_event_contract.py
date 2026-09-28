"""Native LangGraph checkpoint event timing for per-item subgraphs."""

import asyncio
from typing import Annotated, TypedDict

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

ITEM_TAG = "workflow:collect:item"


def merge_results(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    return {**left, **right}


class State(TypedDict):
    results: Annotated[dict[str, str], merge_results]


class SessionState(State):
    session: str


class DelayedTerminalCheckpointSaver(AsyncSqliteSaver):
    def __init__(self, conn):
        super().__init__(conn)
        self.fast_terminal_aput_started = asyncio.Event()
        self.release_fast_terminal_aput = asyncio.Event()
        self.committed_checkpoints: set[tuple[str, str]] = set()

    async def aput(self, config, checkpoint, metadata, new_versions):
        configurable = config["configurable"]
        namespace = configurable["checkpoint_ns"]
        is_fast_terminal = (
            namespace.startswith("fast:")
            and metadata.get("source") == "loop"
            and metadata.get("step") == 1
        )
        if is_fast_terminal:
            self.fast_terminal_aput_started.set()
            await self.release_fast_terminal_aput.wait()

        committed_config = await super().aput(config, checkpoint, metadata, new_versions)
        self.committed_checkpoints.add(
            (committed_config["configurable"]["checkpoint_ns"], committed_config["configurable"]["checkpoint_id"])
        )
        return committed_config


def is_terminal_subgraph_checkpoint(chunk, branch: str) -> bool:
    if not isinstance(chunk, tuple) or len(chunk) != 3:
        return False
    namespace, mode, payload = chunk
    return (
        mode == "checkpoints"
        and len(namespace) == 1
        and namespace[0].startswith(f"{branch}:")
        and payload["metadata"].get("source") == "loop"
        and not payload.get("next")
        and not payload.get("tasks")
    )


@pytest.mark.asyncio
async def test_per_item_terminal_checkpoint_waits_for_sqlite_commit_and_slow_sibling(tmp_path):
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    slow_finished = asyncio.Event()
    fast_terminal_event = asyncio.Event()
    fast_terminal_payload = None

    async def fast_work(_state):
        return {"results": {"fast": "done"}}

    async def slow_work(_state):
        slow_started.set()
        await release_slow.wait()
        slow_finished.set()
        return {"results": {"slow": "done"}}

    def item_subgraph(work):
        builder = StateGraph(State)
        builder.add_node("work", work)
        builder.add_edge(START, "work")
        builder.add_edge("work", END)
        return builder.compile()

    builder = StateGraph(State)
    builder.add_node("fast", item_subgraph(fast_work))
    builder.add_node("slow", item_subgraph(slow_work))
    for branch in ("fast", "slow"):
        builder.add_edge(START, branch)
        builder.add_edge(branch, END)

    async with DelayedTerminalCheckpointSaver.from_conn_string(
        str(tmp_path / "native-events.sqlite")
    ) as saver:
        graph = builder.compile(checkpointer=saver)

        async def consume():
            nonlocal fast_terminal_payload
            async for event in graph.astream_events(
                {"results": {}},
                config={
                    "configurable": {"thread_id": "session-fast-slow"},
                    "metadata": {"sessionID": "session-fast-slow"},
                },
                version="v2",
                stream_mode=["updates", "checkpoints", "tasks"],
                subgraphs=True,
                durability="sync",
            ):
                if event["event"] != "on_chain_stream":
                    continue
                chunk = event["data"]["chunk"]
                if is_terminal_subgraph_checkpoint(chunk, "fast"):
                    fast_terminal_payload = chunk[2]
                    fast_terminal_event.set()

        consumer = asyncio.create_task(consume())
        try:
            async with asyncio.timeout(10):
                await asyncio.gather(saver.fast_terminal_aput_started.wait(), slow_started.wait())

            assert not fast_terminal_event.is_set()
            assert not slow_finished.is_set()

            saver.release_fast_terminal_aput.set()
            async with asyncio.timeout(10):
                await fast_terminal_event.wait()

            configurable = fast_terminal_payload["config"]["configurable"]
            checkpoint_identity = (configurable["checkpoint_ns"], configurable["checkpoint_id"])
            assert checkpoint_identity in saver.committed_checkpoints
            assert fast_terminal_payload["values"]["results"] == {"fast": "done"}
            assert not slow_finished.is_set()

            release_slow.set()
            await consumer
        finally:
            saver.release_fast_terminal_aput.set()
            release_slow.set()
            if not consumer.done():
                consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)


def stream_parts(events):
    for event in events:
        if event["event"] != "on_chain_stream":
            continue
        chunk = event["data"].get("chunk")
        if isinstance(chunk, tuple) and len(chunk) == 3:
            yield chunk


@pytest.mark.asyncio
async def test_v2_stream_maps_root_and_subgraph_events_per_session(tmp_path):
    async def model(state):
        return {"value": state["session"]}

    tagged_model = RunnableLambda(model).with_config(tags=[ITEM_TAG])

    async def work(state, config):
        result = await tagged_model.ainvoke(state, config=config)
        return {"results": {state["session"]: result["value"]}}

    collect = StateGraph(SessionState)
    collect.add_node("work", RunnableLambda(work).with_config(tags=[ITEM_TAG]))
    collect.add_edge(START, "work")
    collect.add_edge("work", END)

    root = StateGraph(SessionState)
    root.add_node("collect", collect.compile().with_config(tags=[ITEM_TAG]))
    root.add_edge(START, "collect")
    root.add_edge("collect", END)

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "sessions.sqlite")) as saver:
        graph = root.compile(checkpointer=saver)

        async def capture(session_id: str):
            events = []
            async for event in graph.astream_events(
                {"session": session_id, "results": {}},
                config={
                    "configurable": {"thread_id": session_id},
                    "metadata": {"sessionID": session_id},
                },
                version="v2",
                stream_mode=["updates", "checkpoints", "tasks"],
                subgraphs=True,
                durability="sync",
            ):
                events.append(event)
            return events

        first_events, second_events = await asyncio.gather(capture("session-one"), capture("session-two"))

        for session_id, events in (("session-one", first_events), ("session-two", second_events)):
            parts = list(stream_parts(events))
            root_updates = [part for part in parts if part[0] == () and part[1] == "updates"]
            child_updates = [part for part in parts if part[0] and part[1] == "updates"]
            root_checkpoints = [part for part in parts if part[0] == () and part[1] == "checkpoints"]
            child_checkpoints = [part for part in parts if part[0] and part[1] == "checkpoints"]
            checkpoint_events = [
                event for event in events
                if event["event"] == "on_chain_stream"
                and isinstance(event["data"].get("chunk"), tuple)
                and len(event["data"]["chunk"]) == 3
                and event["data"]["chunk"][1] == "checkpoints"
            ]

            assert root_updates and "collect" in root_updates[-1][2]
            assert child_updates and "work" in child_updates[-1][2]
            assert root_checkpoints and child_checkpoints
            assert checkpoint_events
            assert all(
                part[2]["config"]["configurable"]["thread_id"] == session_id
                for part in root_checkpoints + child_checkpoints
            )
            assert all(
                event["metadata"].get("sessionID") == session_id
                for event in checkpoint_events
            )

            task_parts = [part for part in parts if part[1] == "tasks"]
            root_collect_tasks = [
                part[2] for part in task_parts
                if part[0] == () and part[2].get("name") == "collect" and "input" in part[2]
            ]
            child_work_tasks = [
                part[2] for part in task_parts
                if part[0] and part[2].get("name") == "work" and "input" in part[2]
            ]
            assert len(root_collect_tasks) == len(child_work_tasks) == 1
            assert root_collect_tasks[0]["metadata"]["sessionID"] == session_id
            assert child_work_tasks[0]["metadata"]["sessionID"] == session_id

            runnable_ids = {event["run_id"] for event in events if event.get("run_id")}
            root_task_id = root_collect_tasks[0]["id"]
            child_task_id = child_work_tasks[0]["id"]
            assert root_task_id not in runnable_ids
            assert child_task_id not in runnable_ids
            assert any(
                f"|work:{child_task_id}" in event["metadata"].get("langgraph_checkpoint_ns", "")
                for event in events
            )

            tagged_ends = [
                event for event in events
                if event["event"] == "on_chain_end" and ITEM_TAG in event["tags"]
            ]
            terminal_child_checkpoints = [
                part for part in child_checkpoints
                if part[2]["metadata"].get("source") == "loop"
                and not part[2].get("next")
                and not part[2].get("tasks")
            ]
            assert len(tagged_ends) > len(terminal_child_checkpoints) == 1

        first_state, second_state = await asyncio.gather(
            graph.aget_state({"configurable": {"thread_id": "session-one"}}),
            graph.aget_state({"configurable": {"thread_id": "session-two"}}),
        )
        assert first_state.values["results"] == {"session-one": "session-one"}
        assert second_state.values["results"] == {"session-two": "session-two"}
