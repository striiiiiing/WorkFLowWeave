"""AI 服务负责请求预算、重试和业务失败结果。"""

import asyncio
import hashlib

from logagent.agent.binding import workflow_mcp_binding
from logagent.errors import LogAgentError
from logagent.models import AnalysisResult, ExecutionContext, copy_model
from logagent.workflow.agent_tasks import execute_agent_task


async def analyze_call(snapshot, ai_service, config, item, text, task_id, result, model, *,
                       agent_service=None, execution_epoch=None, messages=None):
    workflow = snapshot.workflow
    if item.agent_mode:
        if agent_service is None:
            raise LogAgentError("not_ready", "Workflow Agent 服务尚未装配")
        if not execution_epoch:
            raise LogAgentError("invalid_argument", "Workflow Agent 执行缺少持久化轮次身份")
        identity = f"{result.session_id}:{execution_epoch}:{result.stage}:{task_id}"
        return await execute_agent_task(
            agent_service,
            operation_id="workflow_" + hashlib.sha256(identity.encode()).hexdigest(),
            workflow_session_id=result.session_id,
            workflow_task_id=task_id,
            ai_config=copy_model(config),
            model=model,
            workflow_result=text,
            system_prompt=workflow.system_prompt if item.system_prompt is None else item.system_prompt,
            input_prompt=workflow.input_prompt if item.input_prompt is None else item.input_prompt,
            user_prompt=item.user_prompt,
            tool_names=item.agent_tools,
            mcp_binding=workflow_mcp_binding(snapshot),
        )
    raw = await ai_service.execute(
        copy_model(config),
        workflow.input_prompt if item.input_prompt is None else item.input_prompt,
        text,
        model=model,
        task_id=task_id,
        context=ExecutionContext(
            workflow_id=result.workflow_id, session_id=result.session_id, stage=result.stage
        ),
        system_prompt=workflow.system_prompt if item.system_prompt is None else item.system_prompt,
        user_prompt=item.user_prompt,
        **({"messages": messages} if messages is not None else {}),
    )
    if asyncio.current_task().cancelling():
        raise asyncio.CancelledError
    output = AnalysisResult.model_validate(
        raw.model_dump(mode="json") if isinstance(raw, AnalysisResult) else raw
    )
    if output.task_id != task_id:
        raise ValueError("Analysis identity mismatch")
    return output
