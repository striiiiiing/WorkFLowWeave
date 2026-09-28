"""AI 服务负责请求预算、重试和业务失败结果。"""

import asyncio

from logagent.models import AnalysisResult, ExecutionContext, copy_model


async def analyze_call(snapshot, ai_service, config, item, text, task_id, result, model):
    workflow = snapshot.workflow
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
    )
    if asyncio.current_task().cancelling():
        raise asyncio.CancelledError
    output = AnalysisResult.model_validate(
        raw.model_dump(mode="json") if isinstance(raw, AnalysisResult) else raw
    )
    if output.task_id != task_id:
        raise ValueError("Analysis identity mismatch")
    return output
