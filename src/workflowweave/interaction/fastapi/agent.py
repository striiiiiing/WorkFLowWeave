"""Assemble Agent dependencies at the application's composition boundary."""
from __future__ import annotations

import importlib
from pathlib import Path

from workflowweave.agent.config import AgentConfig
from workflowweave.agent.integrations.models import ModelProvider
from workflowweave.agent.integrations.resources import ResourceProvider
from workflowweave.agent.runtime.runner import TurnRunner
from workflowweave.agent.runtime.sessions import SessionManager
from workflowweave.agent.runtime.turns import TurnCoordinator
from workflowweave.agent.service import AgentService
from workflowweave.agent.storage.artifacts import ArtifactStore
from workflowweave.agent.storage.bindings import BindingStore
from workflowweave.agent.storage.checkpoints import CheckpointStore
from workflowweave.agent.storage.invocations import InvocationStore
from workflowweave.agent.storage.sessions import SessionStore
from workflowweave.agent.storage.settings import SettingsStore
from workflowweave.agent.tools.scheduling import ToolScheduler
from workflowweave.agent.workspace.files import WorkspaceBackend
from workflowweave.agent.workspace.sandbox import ShellSandbox
from workflowweave.config.registry import BUILTIN_TOOLS
from workflowweave.models import CollectionContext


def create_agent_service(workspace: Path, runtime: Path, *, config=None,
                         model_provider=None, ai_service=None, ai_config=None, model=None,
                         checkpointer=None, resources=None, plugins=None,
                         collectors=None, channels=None, mcp_runtime=None,
                         mcp_binding_reader=None, declarations=None, gateway_factory=None,
                         collection_context_factory=None, read_only_tools=False):
    runtime = Path(runtime).absolute()
    config = (config or AgentConfig()).model_copy(deep=True)
    backend = WorkspaceBackend(workspace, runtime)
    bindings = BindingStore(runtime.parent / "mcp-bindings")
    settings = SettingsStore(runtime.parent / "config.json")
    checkpoints = CheckpointStore(runtime / "checkpoints.sqlite", saver=checkpointer)
    repository = SessionStore(runtime, backend, bindings, InvocationStore(runtime.parent / "invocations"))
    turns = TurnCoordinator(repository)
    scheduler = ToolScheduler(config.read_concurrency)
    artifacts = ArtifactStore(backend)
    if declarations is None and plugins is None:
        declarations = [importlib.import_module(path).plugin for path in BUILTIN_TOOLS.values()]
    if read_only_tools and declarations is not None:
        declarations = [item for item in declarations if item.execution == "read"]
    publication = ResourceProvider(config=config, resources=resources, plugins=plugins,
                                   declarations=declarations or (), default_model=model,
                                   ai_config=ai_config, has_model_provider=model_provider is not None,
                                   gateway_factory=gateway_factory, mcp_runtime=mcp_runtime,
                                   bindings=bindings)
    models = ModelProvider(provider=model_provider, ai_service=ai_service, ai_config=ai_config)
    runner = TurnRunner(repository=repository, turns=turns, checkpoints=checkpoints,
                        resource_provider=publication, model_provider=models,
                        workspace=backend, scheduler=scheduler, artifacts=artifacts,
                        sandbox_factory=ShellSandbox,
                        collection_context_factory=(collection_context_factory or
                          (lambda session: CollectionContext("agent", session.session_id))))
    sessions = SessionManager(repository, turns, checkpoints, bindings,
                              default_model=model, resources=resources,
                              mcp_binding_reader=mcp_binding_reader,
                              resolve_model=publication.resolve_model if model_provider is None else None)
    service = AgentService(workspace=backend, repository=repository, sessions=sessions,
                           turns=turns, runner=runner, checkpoints=checkpoints,
                           settings=settings, resource_provider=publication)
    sessions.initialize = service.initialize
    turns.run = runner.run
    return service
