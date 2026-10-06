"""Workflow 专属快照和采集、AI、通知替身。

记录调用并支持分析失败/阻塞，供恢复和准入竞争测试控制业务边界；
不访问网络，真实存储与 WorkflowRunner 由各测试自行装配。
"""

import asyncio
from datetime import UTC, datetime

from workflowweave.models import (
    AIConfig,
    AnalysisResult,
    AnalysisTask,
    ChannelConfig,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)


def snapshot(*, channels=True, fan_in=None, tasks=("first", "second"), **options):
    wf = WorkflowDefinition(
        id="demo",
        sources=["source"],
        analyses=[
            AnalysisTask(user_prompt="analyze input", id=key, ai="ai", model="offline", input_prompt=f"{key}: {{input}}")
            for key in tasks
        ],
        channels=["one", "two"] if channels else [],
        fan_in=fan_in,
        **options,
    )
    return WorkflowSnapshot(
        workflow=wf,
        sources={"source": SourceConfig(id="source", call={"kind": "cli", "mode": "argv", "executable": "echo"})},
        ai={"ai": AIConfig(id="ai", provider="mock", models={"offline": {}})},
        channels={
            key: ChannelConfig(id=key, channel="mock", options={"target": key})
            for key in wf.channels
        },
        created_at=datetime.now(UTC),
    )


class Collector:
    def __init__(self):
        self.calls = []

    async def collect(self, config, context):
        self.calls.append(config.id)
        return CollectionResult(
            source_id=config.id, status="success", raw={"stdout": "original data", "stderr": "", "exit_code": 0}
        )


class AI:
    def __init__(self, *, fail=(), block=None):
        self.calls = []
        self.requests = []
        self.fail = set(fail)
        self.block = block
        self.started = asyncio.Event()

    async def execute(self, config, prompt, text, *, model, task_id, context,
                      system_prompt=None, user_prompt="", messages=None):
        self.calls.append((task_id, text, model))
        self.requests.append((task_id, config.id, prompt, system_prompt, user_prompt))
        if task_id == self.block:
            self.started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return AnalysisResult(
                    task_id=task_id,
                    status="cancelled",
                    error=ErrorInfo(code="ai_cancelled", message="AI call cancelled"),
                )
        if task_id in self.fail:
            return AnalysisResult(
                task_id=task_id,
                status="failed",
                error=ErrorInfo(code="test_failure", message="failure"),
            )
        return AnalysisResult(task_id=task_id, status="success", text=f"{task_id}({text})")


class Channel:
    def __init__(self):
        self.calls = []

    async def send(self, config, notification):
        self.calls.append((notification.output_id, config.id, notification.text))
        return DeliveryResult(
            channel_id=config.id, output_id=notification.output_id, status="success", attempts=1
        )


def archived(store, session_id, base):
    """按业务基础键读取最新轮次，仅供测试检查持久化事实。"""
    _, entries = store.entries(session_id)
    return next((entry for entry in reversed(entries)
                 if entry["write_key"] == base or entry["write_key"].startswith(base + ":epoch:")), None)
