"""将系统提示词与任务输入组成独立角色消息，保持输入文本的字面含义。"""

from langchain_core.messages import HumanMessage, SystemMessage


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
