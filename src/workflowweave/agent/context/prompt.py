"""Stable Agent prompt prefix assembled at turn admission."""

from __future__ import annotations

from datetime import datetime

RUNTIME_INSTRUCTION = (
    "运行时文件入口固定为 Runtime/self.json。需要了解当前会话、分支、轮次、来源和工具代次时，"
    "请使用 read 读取该文件；它是只读会话映射，不要写入或通过 grep 搜索。"
)


def build_system_prompt(*, agents: str, session_id: str, branch_id: str,
                        turn_id: str, workspace: str, workflow_session_id: str | None,
                        now: datetime) -> str:
    source = workflow_session_id or "none"
    runtime = (
        f"session={session_id}; branch={branch_id}; turn={turn_id}; "
        f"workflow_session={source}; date={now.date().isoformat()}; workspace={workspace}"
    )
    return f"{RUNTIME_INSTRUCTION}\n运行上下文：{runtime}\n\n工作区常驻规则：\n{agents}".strip()
