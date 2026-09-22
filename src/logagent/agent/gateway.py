"""On-demand access to a round's configured collectors and notification channels."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, ValidationError

from logagent.config.calls import (
    normalize_call_options,
    resolve_channel_call,
    resolve_source_call,
)
from logagent.errors import LogAgentError, validation_error
from logagent.models import (
    ChannelOverride,
    JSONObject,
    Notification,
    SourceOverride,
    StrictModel,
)
from logagent.schema import call_options_schema


class _SourceArguments(StrictModel):
    options: JSONObject = Field(default_factory=dict)
    setters: JSONObject = Field(default_factory=dict)


class _NotificationBody(StrictModel):
    title: str = ""
    text: str
    metadata: JSONObject = Field(default_factory=dict)


class _ChannelArguments(StrictModel):
    options: JSONObject = Field(default_factory=dict)
    notification: _NotificationBody


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
        self.collectors = collectors
        self.channels = channels
        self.data_dir = data_dir
        self._descriptions = {
            "sources": {item.name: item for item in snapshot.collectors.describe()},
            "channels": {item.name: item for item in snapshot.channels.describe()
                         if "notification" in item.capabilities},
        }

    def _target(self, target):
        if not isinstance(target, str) or ":" not in target:
            raise LogAgentError("invalid_target", "目标需要 sources:id 或 channels:id")
        kind, ident = target.split(":", 1)
        resource = self.snapshot.resources.get(kind, {}).get(ident)
        if kind not in self._descriptions or resource is None:
            raise LogAgentError("target_unavailable", "目标未配置或未启用")
        name = resource.collector if kind == "sources" else resource.channel
        description = self._descriptions[kind].get(name)
        if description is None:
            raise LogAgentError("target_unavailable", "目标插件不可调用")
        return kind, resource, description

    def execution(self, arguments):
        if arguments.get("action") in {"list", "schema"}:
            return "read"
        kind, _, description = self._target(arguments.get("target"))
        return "exclusive" if kind == "channels" else description.execution

    def listing(self, *, query="", cursor=0, page_size):
        entries = []
        for kind, resources in self.snapshot.resources.items():
            if kind not in self._descriptions:
                continue
            for ident in sorted(resources):
                resource = resources[ident]
                name = resource.collector if kind == "sources" else resource.channel
                description = self._descriptions[kind].get(name)
                if description is None:
                    continue
                entry = {"target": f"{kind}:{ident}", "description": description.description,
                         "execution": "exclusive" if kind == "channels" else description.execution}
                if query.casefold() in (entry["target"] + entry["description"]).casefold():
                    entries.append(entry)
        end = min(cursor + page_size, len(entries))
        return {"status": "success", "entries": entries[cursor:end], "cursor": cursor,
                "next_cursor": end if end < len(entries) else None}

    def schema(self, target):
        kind, resource, description = self._target(target)
        options = call_options_schema(description.options_schema, resource.options)
        # An embedded schema needs its own local-reference base URI.
        options["$id"] = "urn:logagent:call-options"
        options["description"] = "Only explicit call overrides; saved values remain effective"
        if kind == "sources":
            setters = deepcopy(description.setters_schema)
            setters.setdefault("$id", "urn:logagent:call-setters")
            setters["description"] = "Setter overrides; omitted keys retain the saved values"
            properties = {"options": options, "setters": setters}
            required = ["options"] if options.get("required") else []
        else:
            properties = {"options": options, "notification": _NotificationBody.model_json_schema()}
            required = ["notification", *(["options"] if options.get("required") else [])]
        return {"type": "object", "properties": properties, "required": required,
                "additionalProperties": False}

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
        kind, resource, description = self._target(target)
        try:
            model = _SourceArguments if kind == "sources" else _ChannelArguments
            values = model.model_validate(arguments.get("arguments", {}))
        except ValidationError as exc:
            raise validation_error(exc, code="invalid_argument") from None
        options = normalize_call_options(values.options, description.options_schema,
                                         data_dir=self.data_dir)
        if kind == "sources":
            source = resolve_source_call(resource, {}, SourceOverride(options=options,
                                                                      setters=values.setters))
            result = await self.collectors.collect(source, context.collection)
        else:
            channel = resolve_channel_call(resource, ChannelOverride(options=options))
            # Tool call IDs are provider-controlled and need not satisfy the public ID type.
            output_id = hashlib.sha256(f"{context.turn_id}:{context.tool_call_id}".encode()).hexdigest()
            notification = Notification(session_id=context.session_id, output_id=output_id,
                                        **values.notification.model_dump())
            result = await self.channels.send(channel, notification)
        return result.model_dump(mode="json")
