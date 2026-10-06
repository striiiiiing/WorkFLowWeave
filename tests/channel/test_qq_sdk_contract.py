from __future__ import annotations

import importlib.util
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Notification

_QQ_PLUGIN = Path(__file__).parents[2] / "plugins" / "channel" / "qq" / "channel.py"


class _Token:
    app_id = "test-app"

    async def check_token(self):
        return None

    def get_string(self):
        return "QQBot test-token"


def _load_qq_channel():
    spec = importlib.util.spec_from_file_location("qq_sdk_contract_plugin", _QQ_PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.QQChannel


def _new_channel(botpy, port: int, monkeypatch):
    QQChannel = _load_qq_channel()
    channel = QQChannel(ChannelConfig(
        id="qq-contract",
        channel="qq",
        options={
            "app_id": "test-app",
            "client_secret": {"kind": "env", "name": "QQ_SECRET"},
            "target_kind": "c2c",
            "target_id": "user-1",
        },
    ), credentials=None)
    monkeypatch.setattr(botpy.http.Route, "SCHEME", "http")
    monkeypatch.setattr(botpy.http.Route, "DOMAIN", f"127.0.0.1:{port}")
    client_factory = channel._make_client_factory(botpy)
    client = client_factory(intents=channel._intents(botpy))
    client.http._token = _Token()
    channel._botpy = botpy
    channel._client = client
    return channel, client


@asynccontextmanager
async def _loopback_server(handler):
    from aiohttp import web

    app = web.Application()
    app.router.add_post("/v2/users/{openid}/messages", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        await runner.cleanup()


def _notice() -> Notification:
    return Notification(session_id="session-1", output_id="output-1", text="notice")


def _json_response(web, payload, *, status=200):
    return web.Response(
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        status=status,
    )


@pytest.mark.parametrize(
    ("status", "uncertain"),
    [(401, False), (403, False), (404, False), (405, False), (429, False), (500, True), (504, True)],
)
@pytest.mark.asyncio
async def test_qq_sdk_http_error_delivery_certainty(monkeypatch, status, uncertain):
    botpy = pytest.importorskip("botpy")
    from aiohttp import web

    requests = []

    async def reject(request):
        requests.append(await request.json())
        return _json_response(web, {"message": "rejected"}, status=status)

    async with _loopback_server(reject) as port:
        channel, _client = _new_channel(botpy, port, monkeypatch)
        try:
            with pytest.raises(ChannelDeliveryError) as raised:
                await channel.send(_notice(), options={})
            assert raised.value.uncertain is uncertain
            assert len(requests) == 1
            assert requests[0]["openid"] == "user-1"
            assert requests[0]["content"] == "notice"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_qq_sdk_does_not_retry_post_after_connection_reset(monkeypatch):
    botpy = pytest.importorskip("botpy")
    from aiohttp import web

    requests = []

    async def accept(request):
        requests.append(await request.json())
        return _json_response(web, {"id": "accepted-message"})

    async with _loopback_server(accept) as port:
        channel, client = _new_channel(botpy, port, monkeypatch)
        await client.http.check_session()
        request = client.http._session.request

        def lose_acknowledgement(*args, **kwargs):
            @asynccontextmanager
            async def response_then_reset():
                async with request(*args, **kwargs) as response:
                    yield response
                raise ConnectionResetError("response lost after server acceptance")

            return response_then_reset()

        monkeypatch.setattr(client.http._session, "request", lose_acknowledgement)
        try:
            with pytest.raises(ChannelDeliveryError) as raised:
                await channel.send(_notice(), options={})
            assert raised.value.uncertain is True
            assert len(requests) == 1
            assert requests[0]["openid"] == "user-1"
            assert requests[0]["content"] == "notice"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_qq_sdk_client_keeps_authorization_out_of_debug_logs(monkeypatch, caplog):
    botpy = pytest.importorskip("botpy")
    from aiohttp import web

    async def accept(_request):
        return _json_response(web, {"id": "accepted-message"})

    async with _loopback_server(accept) as port:
        channel, client = _new_channel(botpy, port, monkeypatch)
        try:
            assert logging.getLogger("botpy").level == logging.INFO
            await channel.send(_notice(), options={})
            assert "QQBot test-token" not in caplog.text
        finally:
            await channel.stop()
