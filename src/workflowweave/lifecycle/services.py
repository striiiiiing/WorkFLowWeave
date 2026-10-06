"""向交互层暴露由生命周期统一装配的依赖。"""

from dataclasses import dataclass
from typing import Any

from workflowweave.agent import AgentService
from workflowweave.ai import AIService
from workflowweave.channel import ChannelManager
from workflowweave.collection import CollectorManager
from workflowweave.config import CredentialManager, PluginRegistry, ResourceStore
from workflowweave.models import SystemConfig
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.execution.scheduler import WorkflowScheduler
from workflowweave.workflow.storage.facts import SessionStore
from workflowweave.workflow.storage.sessions import SessionView


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
