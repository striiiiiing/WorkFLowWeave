from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Notification

_QQ_PLUGIN = (
    Path(__file__).parents[2]
    / "src"
    / "workflowweave"
    / "plugins"
    / "channel"
    / "qq"
    / "channel.py"
)


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


@pytest.mark.asyncio
async def test_qq_sdk_rest_and_gateway_sessions_honor_environment_proxy(monkeypatch):
    botpy = pytest.importorskip("botpy")
    gateway_module = importlib.import_module("botpy.gateway")
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:8080")
    monkeypatch.delenv("ws_proxy", raising=False)
    monkeypatch.delenv("WS_PROXY", raising=False)
    monkeypatch.delenv("wss_proxy", raising=False)
    monkeypatch.delenv("WSS_PROXY", raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    sessions = []

    class _WebSocket:
        closed = False

        async def receive(self):
            await asyncio.Future()

    class _WebSocketContext:
        async def __aenter__(self):
            return _WebSocket()

        async def __aexit__(self, *_args):
            return None

    class _GatewaySession:
        def __init__(self, *, connector, trust_env=False):
            self.connector = connector
            self.trust_env = trust_env
            sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def ws_connect(self, _url, *, proxy):
            assert proxy == "http://proxy.invalid:8080"
            return _WebSocketContext()

    monkeypatch.setattr(gateway_module, "ClientSession", _GatewaySession)
    channel, client = _new_channel(botpy, 0, monkeypatch)
    try:
        await client.http.check_session()
        assert client.http._session._trust_env is True

        client._connection = SimpleNamespace(parser={})
        gateway_task = asyncio.create_task(client.bot_connect({"url": "ws://gateway.invalid"}))
        await asyncio.sleep(0)
        assert sessions and sessions[0].trust_env is True
        gateway_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gateway_task
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_qq_sdk_token_authentication_and_refresh_use_environment_proxy(monkeypatch, rejected):
    botpy = pytest.importorskip("botpy")
    token_type = importlib.import_module("botpy.robot").Token
    aiohttp = importlib.import_module("aiohttp")
    session_factory = aiohttp.ClientSession
    requests = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self):
            if rejected:
                return {"code": 100016}
            return {"access_token": f"token-{len(requests)}", "expires_in": "7200"}

    class TokenSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def post(self, url, *, timeout, json):
            assert url == "https://bots.qq.com/app/getAppAccessToken"
            assert timeout.total == 30.0
            assert json == {"appId": "test-app", "clientSecret": "test-secret"}
            requests.append(json)
            return Response()

    def make_session(**kwargs):
        assert kwargs["trust_env"] is True
        return session_factory(**kwargs) if "connector" in kwargs else TokenSession()

    async def me(_http, _route, **_kwargs):
        return {"id": "123", "username": "bot"}

    monkeypatch.setattr(aiohttp, "ClientSession", make_session)
    monkeypatch.setattr(botpy.http.BotHttp, "request", me)
    channel, client = _new_channel(botpy, 0, monkeypatch)
    token = token_type(app_id="test-app", secret="test-secret")
    try:
        if rejected:
            with pytest.raises(ChannelDeliveryError) as raised:
                await client.http.login(token)
            assert raised.value.code == "qq_authentication_rejected"
            assert raised.value.info.message == (
                "QQ Bot 凭据无效（100016）：请核对该机器人的 AppID 和当前 Client Secret，"
                "并确认没有使用已重置的旧密钥"
            )
            assert raised.value.details == {"http_status": 200, "platform_code": 100016}
            assert len(requests) == 1
            return
        await client.http.login(token)
        assert client.http._token is token
        assert token.access_token == "token-1"
        assert client.http._session.trust_env is True
        token.expires_in = 0
        await token.check_token()
        assert token.access_token == "token-2"
        assert len(requests) == 2
    finally:
        await channel.stop()


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


@pytest.mark.asyncio
async def test_qq_sdk_client_does_not_install_synchronous_file_handler(monkeypatch):
    botpy = pytest.importorskip("botpy")
    from logging.handlers import TimedRotatingFileHandler

    channel, _client = _new_channel(botpy, 0, monkeypatch)
    try:
        logger = logging.getLogger("botpy")
        assert not any(isinstance(handler, TimedRotatingFileHandler) for handler in logger.handlers)
        assert logger.propagate is True
    finally:
        await channel.stop()
