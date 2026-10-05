"""Agent use-case facade with explicitly assembled dependencies."""
from __future__ import annotations

from typing import Any

from logagent.agent.config import AgentConfig


class AgentService:
    def __init__(self, *, workspace, repository, sessions, turns, runner,
                 checkpoints, settings, resource_provider):
        self.workspace = workspace
        self.repository = repository
        self.session_manager = sessions
        self.turns = turns
        self.runner = runner
        self.checkpoints = checkpoints
        self.settings = settings
        self.resource_provider = resource_provider
        self._initialized = False

    @property
    def config(self):
        return self.resource_provider.config

    @property
    def sessions(self):
        return self.repository.views

    @property
    def accepting(self):
        return self.turns.accepting

    @property
    def scheduler(self):
        return self.runner.scheduler

    @property
    def model_provider(self):
        """Expose the injected test/embedded provider without owning it."""
        return self.runner.model_provider.model_provider

    @model_provider.setter
    def model_provider(self, provider):
        self.runner.model_provider.model_provider = provider
        self.resource_provider.model_provider = provider is not None

    @property
    def runtime(self):
        return self.repository.runtime

    @property
    def checkpointer(self):
        return self.checkpoints.saver

    async def initialize(self):
        if self._initialized:
            return
        self.resource_provider.config = self.settings.load(self.config)
        await self.workspace.initialize()
        if not (self.workspace.root / "AGENTS.md").exists():
            await self.workspace.write("AGENTS.md", "overwrite", (
                "协助用户分析日志和 Workflow 结果。用 mcp 按需加载目录、发现工具、读取完整 schema 并调用原始 MCP。\n"
                "通过 read(\"Runtime/self.json\") 查看当前会话与来源。read/grep 用于查阅文件；"
                "在相应写能力可用且值得长期保存时，用 write 维护 Memory/YYYY-MM-DD.md 或 History/<session>.md。\n"
                "Shell 是单次执行；同组工具可并发，有前后依赖的调用分成两个模型步骤。"
                "工具结果未知时告知用户，不自动重做副作用。\n"
            ), expected_hash="*")
        await self.checkpoints.initialize()
        await self.repository.restore()
        self._initialized = True

    async def close(self):
        await self.turns.close()
        await self.checkpoints.close()

    async def pause_admission(self):
        return await self.turns.pause_admission()

    def resume_admission(self):
        self.turns.resume_admission()

    async def create_session(self, **options):
        return await self.session_manager.create_session(**options)

    async def fork(self, session_id, **options):
        return await self.session_manager.fork(session_id, **options)

    async def history(self, session_id):
        return await self.session_manager.history(session_id)

    async def set_model(self, session_id, model):
        return await self.session_manager.set_model(session_id, model)

    async def set_title(self, session_id, title):
        return await self.session_manager.set_title(session_id, title)

    def model_views(self):
        return self.session_manager.model_views()

    async def source(self, session_id):
        return await self.session_manager.source(session_id)

    async def get_session(self, session_id):
        return await self.session_manager.get_session(session_id)

    async def list_sessions(self):
        return await self.session_manager.list_sessions()

    async def submit(self, session_id, text, *, request_id):
        return await self.turns.submit(session_id, text, request_id=request_id)

    async def submit_after_idle(self, session_id, text, *, request_id, valid=None):
        return await self.turns.submit_after_idle(session_id, text, request_id=request_id, valid=valid)

    async def append(self, session_id, text, *, request_id):
        return await self.turns.append(session_id, text, request_id=request_id)

    async def wait(self, turn_id):
        return await self.turns.wait(turn_id)

    async def cancel(self, session_id):
        return await self.turns.cancel(session_id)

    async def compact(self, session_id):
        return await self.turns.compact(session_id)

    async def events(self, session_id, *, after=0):
        return await self.repository.log(session_id).replay(after)

    async def wait_events(self, session_id, *, after=0, wait_seconds=0.5):
        return await self.repository.log(session_id).wait_for_events(after, wait_seconds=wait_seconds)

    def tool_views(self):
        return self.resource_provider.tool_views()

    def update_config(self, config: AgentConfig) -> dict[str, Any]:
        self.settings.save(config)
        self.resource_provider.config = config.model_copy(deep=True)
        return self.config.model_dump(mode="json")
