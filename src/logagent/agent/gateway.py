"""On-demand access to a round's configured collectors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from logagent.collection.invocation import CollectorInvocation
from logagent.errors import LogAgentError


@dataclass(frozen=True)
class InvocationSnapshot:
    generation: int
    resources: dict
    collectors: object
    channels: object
    tools: object


class PluginGateway:
    def __init__(self, snapshot: InvocationSnapshot, *, collectors, channels, data_dir: Path):
        self.snapshot = snapshot
        self._calls = CollectorInvocation(
            snapshot.resources.get("sources", {}), snapshot.collectors.describe(),
            executor=collectors, data_dir=data_dir,
        )

    def _target(self, target):
        if not isinstance(target, str) or ":" not in target:
            raise LogAgentError("invalid_target", "目标需要 sources:id")
        kind, ident = target.split(":", 1)
        if kind != "sources":
            raise LogAgentError("target_unavailable", "目标未配置或未启用")
        return self._calls.target(ident)

    def execution(self, arguments):
        if arguments.get("action") in {"list", "schema"}:
            return "read"
        _, description = self._target(arguments.get("target"))
        return description.execution

    def listing(self, *, query="", cursor=0, page_size):
        entries = []
        for kind, resources in self.snapshot.resources.items():
            if kind != "sources":
                continue
            for ident in sorted(resources):
                resource = resources[ident]
                name = resource.collector
                description = self._calls.descriptions.get(name)
                if description is None or not resource.enabled:
                    continue
                entry = {"target": f"{kind}:{ident}", "description": description.description,
                         "execution": description.execution}
                if query.casefold() in (entry["target"] + entry["description"]).casefold():
                    entries.append(entry)
        end = min(cursor + page_size, len(entries))
        return {"status": "success", "entries": entries[cursor:end], "cursor": cursor,
                "next_cursor": end if end < len(entries) else None}

    def schema(self, target):
        resource, _ = self._target(target)
        return self._calls.schema(resource.id)

    async def catalog(self, workspace, *, revision: str):
        # Resource edits can change defaults without changing plugin generation.
        prefix = f"Catalog/{self.snapshot.generation}/{revision}"
        entries = self.listing(page_size=sum(len(items) for items in self.snapshot.resources.values()))
        for item in entries["entries"]:
            path = f"{prefix}/{item['target'].replace(':', '-')}.json"
            await workspace.save_runtime(path, json.dumps(self.schema(item["target"]),
                                                         ensure_ascii=False, indent=2).encode())
            item["schema_path"] = path
        await workspace.save_runtime(prefix + "/index.json",
                                     json.dumps(entries, ensure_ascii=False, indent=2).encode())
        return prefix

    async def invoke(self, arguments, context):
        action = arguments["action"]
        if action == "list":
            return self.listing(query=arguments.get("query", ""), cursor=arguments.get("cursor", 0),
                                page_size=context.config.plugin_page_size)
        target = arguments.get("target")
        if action == "schema":
            return {"status": "success", "target": target, "schema": self.schema(target)}
        if action != "call":
            raise LogAgentError("invalid_argument", "未知 plugin action")
        resource, _ = self._target(target)
        result = await self._calls.invoke(
            resource.id, arguments.get("arguments", {}), context.collection,
        )
        return result.model_dump(mode="json")
