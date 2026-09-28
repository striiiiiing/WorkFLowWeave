"""向交互层暴露由生命周期统一装配的依赖。"""

from dataclasses import dataclass
from typing import Any

from logagent.agent import AgentService
from logagent.ai import AIService
from logagent.channel import ChannelManager
from logagent.collection import CollectorManager
from logagent.config import CredentialManager, PluginRegistry, ResourceStore
from logagent.models import SystemConfig
from logagent.workflow.storage.facts import SessionStore
from logagent.workflow.storage.sessions import SessionView
from logagent.workflow.execution.scheduler import WorkflowScheduler
from logagent.workflow.execution.runner import WorkflowRunner


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """提供已装配服务的固定引用，供 Interaction 注入。

    frozen 仅阻止容器字段被重新赋值，所引用的组件仍有可变运行状态。
    容器不创建或释放资源，所有权由 ApplicationLifecycle 管理。
    """

    system_config: SystemConfig
    credentials: CredentialManager
    plugins: PluginRegistry
    resources: ResourceStore
    session_store: SessionStore
    session_view: SessionView
    checkpointer: Any
    collectors: CollectorManager
    ai: AIService
    channels: ChannelManager
    workflow: WorkflowRunner
    intervals: WorkflowScheduler
    log_path: str | None
    agent: AgentService | None = None
