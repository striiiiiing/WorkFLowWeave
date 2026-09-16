"""Offline request, budget, cancellation and client ownership regressions."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from logagent.ai import AIService, HTTPProvider, MockProvider
from logagent.ai.service import ProviderError
from logagent.errors import LogAgentError
from logagent.models import AIConfig, AnalysisTask, FanInConfig


def config(**changes):
    return AIConfig(id="ai", provider="http", models={"one": {}, "two": {}},
                    base_url="https://model.invalid/v1", **changes)


async def test_http_roles_model_extensions_literal_prompt_and_usage():
    requests = []
    async def transport(request):
        requests.append(request)
        assert request.extensions["timeout"] == dict(connect=None, read=None, write=None, pool=None)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "答案"}}], "usage": {"total_tokens": 3},
        })
    class Credentials:
        async def resolve(self, credential):
            return "test-secret"
    cfg = config(api_key={"kind": "env", "name": "KEY"})
    cfg.system_prompt = "system {input}"
    cfg.models["two"] = {"reasoning_effort": "high", "vendor": {"enabled": True}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(providers={"http": HTTPProvider(client)}, credential_resolver=Credentials())
        result = await service.execute(cfg, "read {input}", "{input} {other}", model="two")
        assert result.status == "success" and result.usage == {"total_tokens": 3}
        payload = json.loads(requests[0].content)
        assert payload == {
            "model": "two", "reasoning_effort": "high", "vendor": {"enabled": True},
            "messages": [{"role": "system", "content": "system {input}"},
                         {"role": "user", "content": "read {input} {other}"}],
        }
        assert str(requests[0].url) == "https://model.invalid/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer test-secret"
        await service.close()
        assert not client.is_closed


@pytest.mark.parametrize("field", ["model", "messages", "temperature", "top_k", "api_key",
                                   "base_url", "timeout", "max_retries", "stream", "extra_body"])
def test_validate_every_model_and_block_managed_fields(field):
    service = AIService(providers={"http": MockProvider()})
    cfg = config()
    cfg.models["two"] = {field: "private"}
    with pytest.raises(LogAgentError) as error:
        service.validate(cfg, "one")
    assert error.value.code == "invalid_config"
    assert "private" not in error.value.info.model_dump_json()


@pytest.mark.parametrize("models", [{}, {"": {}}, {"   ": {}}, {"one": {"bad": float("nan")}}])
def test_models_are_nonempty_json_and_no_implicit_default(models):
    with pytest.raises(ValidationError):
        AIConfig(id="ai", provider="mock", models=models)


def test_tasks_choose_model_explicitly_and_fanin_pairs_resource_and_model():
    with pytest.raises(ValidationError):
        AnalysisTask(id="task", ai="ai")
    for kwargs in ({"ai": "ai"}, {"model": "one"}):
        with pytest.raises(ValidationError):
            FanInConfig(**kwargs)
    assert FanInConfig().model is None
    assert config().timeout == 600 and config().retries == 5
    with pytest.raises(ValidationError):
        AIConfig(id="ai", provider="mock", model="legacy")


async def test_injected_provider_and_arguments_are_isolated_between_retries(monkeypatch):
    monkeypatch.setattr("logagent.ai.service._RETRY_DELAY", 0)
    received = []
    async def responder(**kwargs):
        received.append(kwargs["config"].model_dump())
        kwargs["config"].models["one"]["nested"] = ["mutated"]
        if len(received) == 1:
            raise ProviderError("busy", "test-secret", retryable=True)
        return {"text": kwargs["user"]}
    cfg = AIConfig(id="ai", provider="custom", models={"one": {"nested": ["original"]}})
    service = AIService(providers={"custom": MockProvider(responder)})
    result = await service.execute(cfg, "prefix", "body", model="one")
    assert result.text == "prefix\n\nbody"
    assert received[0] == received[1] == cfg.model_dump()
    await service.close()


@pytest.mark.parametrize("failure,retryable,uncertain", [
    (httpx.ConnectTimeout, True, False), (httpx.ConnectError, True, False),
    (httpx.PoolTimeout, True, False), (429, True, False),
    (httpx.ReadTimeout, False, True), (httpx.WriteError, False, True),
    (httpx.RemoteProtocolError, False, True), (500, False, True),
    (503, False, True), (401, False, False), (403, False, False), (400, False, False),
    (RuntimeError, False, False),
])
async def test_only_confirmed_unaccepted_failures_retry(monkeypatch, failure, retryable, uncertain):
    monkeypatch.setattr("logagent.ai.service._RETRY_DELAY", 0)
    calls = 0
    async def transport(request):
        nonlocal calls
        calls += 1
        if isinstance(failure, int):
            return httpx.Response(failure, text="test-secret")
        raise failure("test-secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(providers={"http": HTTPProvider(client)})
        result = await service.execute(config(), "", "body", model="one")
        assert result.status == "failed"
        assert calls == (6 if retryable else 1)
        assert bool(result.error.details.get("uncertain")) == uncertain
        assert "test-secret" not in result.model_dump_json()
        await service.close()


@pytest.mark.parametrize("body", [
    {}, {"choices": []}, {"choices": [{"message": {"content": ""}}]},
    {"choices": [{"message": {"content": "yes"}}], "usage": []},
    {"choices": [{"message": {"content": "yes"}}], "error": {"key": "test-secret"}},
    {"choices": [{"message": {"content": ["bad"]}}]},
])
async def test_malformed_response_is_failure_without_retry(body):
    calls = 0
    def transport(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(providers={"http": HTTPProvider(client)})
        result = await service.execute(config(), "", "body", model="one")
        assert result.error.code == "invalid_response" and calls == 1
        assert "test-secret" not in result.model_dump_json()
        await service.close()


async def test_total_timeout_includes_credentials_and_starts_no_request():
    calls = []
    class Credentials:
        async def resolve(self, value):
            await asyncio.Future()
    provider = MockProvider(lambda **kwargs: calls.append(kwargs))
    service = AIService(providers={"http": provider}, credential_resolver=Credentials())
    result = await service.execute(config(timeout=.02, api_key={"kind": "env", "name": "KEY"}),
                                   "", "body", model="one")
    assert result.status == "timeout" and calls == []
    await service.close()


async def test_total_timeout_includes_retry_backoff():
    calls = []
    def responder(**kwargs):
        calls.append(kwargs)
        raise ProviderError("busy", "private", retryable=True)
    service = AIService(providers={"http": MockProvider(responder)})
    result = await service.execute(config(timeout=.02), "", "body", model="one")
    assert result.status == "timeout" and len(calls) == 1
    await service.close()


@pytest.mark.parametrize("phase", ["request", "backoff", "swallowed"])
async def test_cancellation_does_not_start_another_request(phase):
    entered = asyncio.Event()
    calls = []
    async def responder(**kwargs):
        calls.append(kwargs)
        entered.set()
        if phase == "backoff":
            raise ProviderError("busy", "private", retryable=True)
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            if phase != "swallowed":
                raise
            return {"text": "must not succeed"}
    service = AIService(providers={"http": MockProvider(responder)})
    task = asyncio.create_task(service.execute(config(), "", "body", model="one"))
    await entered.wait()
    task.cancel()
    result = await task
    assert result.status == "cancelled" and len(calls) == 1
    await service.close()


async def test_missing_credential_resolver_fails_before_provider():
    service = AIService(providers={"http": MockProvider()})
    result = await service.execute(config(api_key={"kind": "env", "name": "KEY"}),
                                   "", "body", model="one")
    assert result.error.code == "credential_resolver_missing"
    await service.close()


async def test_close_is_bounded_idempotent_and_attempts_all_clients():
    closed = []
    class Client(MockProvider):
        def __init__(self, kind):
            self.kind = kind
        async def close(self):
            closed.append(self.kind)
            if self.kind == "hang":
                await asyncio.Future()
            if self.kind == "fail":
                raise OSError("test-secret")
    healthy = Client("ok")
    service = AIService(providers={"a": Client("hang"), "b": Client("fail"),
                                   "c": healthy, "alias": healthy}, close_timeout=.02)
    results = await asyncio.gather(service.close(), service.close(), return_exceptions=True)
    assert all(isinstance(result, LogAgentError) for result in results)
    assert sorted(closed) == ["fail", "hang", "ok"]
    with pytest.raises(LogAgentError) as error:
        await service.close()
    assert "test-secret" not in error.value.info.model_dump_json()
    assert "TimeoutError" in error.value.details["failures"]
    result = await service.execute(config(), "", "body", model="one")
    assert result.error.code == "ai_closed"


async def test_credential_and_request_share_the_same_deadline(monkeypatch):
    clock = [0.0]
    loop = asyncio.get_running_loop()
    original_time = loop.time
    monkeypatch.setattr(loop, "time", lambda: original_time() + clock[0])
    entered = asyncio.Event()
    class Credentials:
        async def resolve(self, credential):
            clock[0] += 40
            return "private"
    async def responder(**kwargs):
        entered.set()
        clock[0] += 25
        await asyncio.Future()
    service = AIService(providers={"http": MockProvider(responder)}, credential_resolver=Credentials())
    result = await service.execute(
        config(timeout=60, api_key={"kind": "env", "name": "KEY"}), "", "body", model="one",
    )
    assert entered.is_set() and result.status == "timeout"
    await service.close()


async def test_owned_http_client_has_no_hidden_short_timeout():
    provider = HTTPProvider()
    assert provider.client.timeout == httpx.Timeout(None)
    await provider.close()
    assert provider.client.is_closed
