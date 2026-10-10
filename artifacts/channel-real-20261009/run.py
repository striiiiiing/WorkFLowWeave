"""Explicit live channel smoke test using saved resources, without email."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import TypeAdapter

from workflowweave.channel import ChannelManager
from workflowweave.config import PluginRegistry
from workflowweave.config.credentials import CredentialManager
from workflowweave.config.reader import ConfigurationReader, read_json
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import ChannelConfig, Credential, Notification


async def feishu_auth(config, credentials):
    secret = await credentials.resolve(TypeAdapter(Credential).validate_python(
        config.options["app_secret"]
    ))
    async with httpx.AsyncClient(timeout=config.timeout) as client:
        response = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": config.options["app_id"], "app_secret": secret},
        )
        response.raise_for_status()
        body = response.json()
    return {
        "status": "success" if body.get("code") == 0 and body.get("tenant_access_token")
        else "failed",
        "platform_code": body.get("code"),
        "http_status": response.status_code,
    }


async def conversation_check(manager, config, notification, wait_seconds):
    """Use the first private inbound route, never a configured notification target."""
    config = config.model_copy(update={"agent_enabled": True}, deep=True)
    received = asyncio.Event()
    entry = {"mode": "conversation", "target_source": "first_private_inbound_event",
             "ignored_non_private_events": 0}
    attempted = False
    started = asyncio.get_running_loop().time()
    entry["stage"] = "receiver_starting"

    async def reply(message):
        nonlocal attempted
        if config.channel == "qq" and message.address.kind != "c2c":
            entry["ignored_non_private_events"] += 1
            return {"status": "accepted"}
        if config.channel == "telegram" and int(message.address.target) <= 0:
            entry["ignored_non_private_events"] += 1
            return {"status": "accepted"}
        if attempted:
            return {"status": "duplicate"}
        attempted = True
        result = await manager.send(config, notification, reply_to=message.address)
        entry.update(status=result.status, delivery=result.model_dump(mode="json"),
                     route_kind=message.address.kind, inbound_received=True)
        received.set()
        return {"status": "accepted"}

    try:
        # Feishu includes chat_type in its SDK event; filter before normalization.
        if config.channel == "feishu":
            channel = manager._register.get(config.channel)
            key = await manager._begin_send(config)
            try:
                instance = await manager._entry(key, channel, config,
                    deadline=asyncio.get_running_loop().time() + config.timeout)
            finally:
                manager._end_send()
            original = instance.instance._handle_event

            async def private_event(data):
                event = data.get("event", data) if isinstance(data, dict) else data.event
                message = event.get("message") if isinstance(event, dict) else event.message
                chat_type = message.get("chat_type") if isinstance(message, dict) else message.chat_type
                if chat_type != "p2p":
                    entry["ignored_non_private_events"] += 1
                    return
                await original(data)

            instance.instance._handle_event = private_event
        await manager.start_receiving(config, reply)
        entry["startup_seconds"] = round(asyncio.get_running_loop().time() - started, 2)
        entry["stage"] = "waiting_first_message"
        instance = manager.receiver(config)
        if config.channel == "feishu":
            entry["connected"] = instance._websocket is not None and instance._websocket._conn is not None
        elif config.channel == "telegram":
            entry["connected"] = bool(instance._application.updater.running)
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while not received.is_set() and asyncio.get_running_loop().time() < deadline:
            if config.channel == "qq":
                state = instance.receiver_status()
                entry["receiver_state"] = state["state"]
                entry["connected"] = state["state"] == "running"
                if state["state"] == "failed":
                    entry["status"] = "receiver_failed"
                    return entry
            await asyncio.sleep(0.5)
        if not received.is_set():
            entry["status"] = "awaiting_first_message" if entry.get("connected") else "not_connected"
            entry["inbound_received"] = False
        return entry
    except Exception as exc:
        entry.update(status="failed", exception_type=type(exc).__name__,
                     elapsed_seconds=round(asyncio.get_running_loop().time() - started, 2))
        causes = []
        cause = exc.__cause__
        while cause is not None:
            causes.append(type(cause).__name__)
            cause = cause.__cause__
        entry["cause_types"] = causes
        if isinstance(exc, WorkFLowWeaveError):
            entry["code"] = exc.code
            entry["details"] = exc.details
        return entry
    finally:
        await manager.stop_receiving(config)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", help="Load channels from this running backend instead of disk")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--channel", help="Limit this run to one non-email capability")
    parser.add_argument("--mode", choices=["send", "conversation"], default="send")
    parser.add_argument("--wait-seconds", type=float, default=30,
                        help="First-message observation window after receiver startup")
    parser.add_argument("--output", default=str(Path(__file__).with_name("result.json")))
    args = parser.parse_args()
    system = await ConfigurationReader().load_system(args.config)
    credentials = CredentialManager(system)
    registry = PluginRegistry()
    await registry.discover_plugins(system)
    manager = ChannelManager(registry.channelRegister, credentials=credentials)
    if args.api:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(args.api + "/api/channels")
            response.raise_for_status()
            items = response.json()
    else:
        resources = await asyncio.to_thread(read_json, Path(system.data_dir) / "resources.json")
        items = resources["channels"].values()
    configs = [ChannelConfig.model_validate(item) for item in items
               if item["channel"] != "email"
               and (args.channel is None or item["channel"] == args.channel)
               and (args.mode != "conversation" or item["channel"] in {"qq", "feishu", "telegram"})]
    marker = "LOGAGENT_CHANNEL_TEST_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {"started_at": datetime.now(UTC).isoformat(), "marker": marker,
              "email_excluded": True, "source": "api" if args.api else "saved_resources_read_only",
              "instances": []}

    async def check(config):
        entry = {"id": config.id, "channel": config.channel, "enabled": config.enabled}
        report["instances"].append(entry)
        if not config.enabled:
            entry["status"] = "disabled"
            return
        if config.channel == "feishu":
            try:
                entry["authentication"] = await feishu_auth(config, credentials)
            except Exception as exc:
                entry["authentication"] = {"status": "failed",
                    "exception_type": type(exc).__name__}
                if isinstance(exc, WorkFLowWeaveError):
                    entry["authentication"]["code"] = exc.code
        notification = Notification(session_id="channel_live_test", output_id=marker,
            title="LogAgent channel test", text="[LogAgent 测试消息] " + marker)
        if args.mode == "conversation":
            entry.update(await conversation_check(manager, config, notification, args.wait_seconds))
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            return
        try:
            result = await manager.send(config, notification)
            entry["delivery"] = result.model_dump(mode="json")
            entry["status"] = result.status
            if result.error and result.error.code == "qq_target_missing":
                entry["authentication"] = {"status": "success"}
            if config.channel == "file" and result.status == "success":
                path = Path(config.options["path"])
                content = await asyncio.to_thread(path.read_text, encoding="utf-8")
                entry["file_readback"] = marker in content
                entry["file_path"] = str(path)
                if not entry["file_readback"]:
                    entry["status"] = "failed_readback"
        except Exception as exc:
            entry["status"] = "failed"
            entry["exception_type"] = type(exc).__name__
            if isinstance(exc, WorkFLowWeaveError):
                entry["code"] = exc.code
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    try:
        await asyncio.gather(*(check(config) for config in configs))
    finally:
        try:
            await manager.stop()
            report["cleanup"] = "success"
        except Exception as exc:
            report["cleanup"] = {"status": "failed", "exception_type": type(exc).__name__}
        report["finished_at"] = datetime.now(UTC).isoformat()
        await asyncio.to_thread(Path(args.output).write_text,
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(entry["status"] != "success" for entry in report["instances"]):
        return 1
    return 0 if report["cleanup"] == "success" else 1


if __name__ == "__main__":
    # SDK transport logs can include credential-bearing endpoints. The report
    # exposes structured errors and stages without copying those URLs.
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
