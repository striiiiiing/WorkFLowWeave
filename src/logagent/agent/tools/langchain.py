"""Translate a genuine ToolRuntime call into the one Agent tool executor."""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import InjectedToolArg, StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime

from logagent.agent.runtime.context import AgentContext
from logagent.agent.tools.executor import execute_tool
from logagent.errors import LogAgentError


def langchain_tool(declaration):
    async def invoke(runtime: Annotated[ToolRuntime, InjectedToolArg], **arguments):
        context = runtime.context
        if not isinstance(context, AgentContext):
            raise LogAgentError("runtime_context_missing", "LangGraph 未注入 Agent turn context")
        tool_call_id = runtime.tool_call_id
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise LogAgentError("tool_call_id_missing", "工具执行缺少 LangGraph tool_call_id")
        return await execute_tool(declaration, arguments, context, tool_call_id=tool_call_id)
    return StructuredTool.from_function(
        coroutine=invoke, name=declaration.name, description=declaration.description,
        args_schema=declaration.input_schema, infer_schema=False,
    )


def build_tools(declarations):
    return [langchain_tool(item) for item in declarations]
