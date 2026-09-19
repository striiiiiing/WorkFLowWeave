"""将系统提示词与任务输入组成独立角色消息，保持输入文本的字面含义。"""

from langchain_core.messages import HumanMessage, SystemMessage


def build_messages(system_prompt: str, prompt: str, input_text: str):
    """构造一个 SystemMessage 和一个 HumanMessage，不修改系统提示词。

    任务提示词含 {input} 时执行字面替换，否则用两个换行追加完整输入。
    输入中其他花括号不作为模板语法解析，替换后的文本也不再次展开。

    Raises:
        TypeError: 任一提示词或输入不是字符串。
    """
    if not all(isinstance(value, str) for value in (system_prompt, prompt, input_text)):
        raise TypeError("AI prompts and input must be strings")
    user = prompt.replace("{input}", input_text) if "{input}" in prompt else f"{prompt}\n\n{input_text}"
    return [SystemMessage(content=system_prompt), HumanMessage(content=user)]
