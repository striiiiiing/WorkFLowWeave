"""将系统提示词与任务输入组成独立角色消息，保持输入文本的字面含义。"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def uses_single_task_optimization(workflow) -> bool:
    fan_in = workflow.fan_in
    if fan_in is None or fan_in.agent_mode or not fan_in.single_task_optimization:
        return False
    if len(workflow.analyses) != 1:
        return False
    task = workflow.analyses[0]
    reused = fan_in.reused_task(workflow.analyses)
    selection = (reused.ai, reused.model) if reused else (fan_in.ai, fan_in.model)
    return selection == (task.ai, task.model)


def optimized_summary_messages(workflow, analyses, shared_input):
    """复现单任务的冻结请求前缀，Agent 汇总始终不复用。"""
    if not uses_single_task_optimization(workflow):
        return None
    task = workflow.analyses[0]
    result = analyses[task.id]
    if result["status"] != "success":
        return None
    return [
        *build_messages(
            workflow.system_prompt if task.system_prompt is None else task.system_prompt,
            workflow.input_prompt if task.input_prompt is None else task.input_prompt,
            shared_input,
            user_prompt=task.user_prompt,
        ),
        AIMessage(content=result["text"]),
        HumanMessage(content=workflow.fan_in.user_prompt),
    ]


def build_messages(system_prompt: str, input_prompt: str, input_text: str, *, user_prompt: str = ""):
    """构造系统、输入与可选差异指令消息，不修改系统提示词。

    输入模板含 {input} 时执行一次字面替换，否则将完整输入放在模板前面。
    输入中其他花括号不作为模板语法解析，替换后的文本也不再次展开。

    Raises:
        TypeError: 任一提示词或输入不是字符串。
    """
    if not all(isinstance(value, str) for value in (system_prompt, input_prompt, input_text, user_prompt)):
        raise TypeError("AI prompts and input must be strings")
    user = (
        input_prompt.replace("{input}", input_text)
        if "{input}" in input_prompt
        else f"{input_text}\n\n{input_prompt}" if input_prompt else input_text
    )
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user)]
    if user_prompt:
        messages.append(HumanMessage(content=user_prompt))
    return messages
