"""Offline request, budget, cancellation and client ownership regressions."""

import asyncio
import json

import httpx
import pytest
from ai_helpers import TestModelFactory
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from logagent.ai import AIService, OpenAIModelFactory
from logagent.ai.service import ModelError
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
            "choices": [{"message": {"role": "assistant", "content": "答案"}}], "usage": {"total_tokens": 3},
        })
    class Credentials:
        async def resolve(self, credential):
            return "test-secret"
    cfg = config(api_key={"kind": "env", "name": "KEY"})
    cfg.system_prompt = "system {input}"
    cfg.models["two"] = {"reasoning_effort": "high", "vendor": {"enabled": True}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)}, credential_resolver=Credentials())
        result = await service.execute(cfg, "read {input}", "{input} {other}", model="two")
        assert result.status == "success"
        assert result.usage["total_tokens"] == 3
        payload = json.loads(requests[0].content)
        assert payload == {
            "model": "two", "stream": False, "reasoning_effort": "high", "vendor": {"enabled": True},
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
    service = AIService(model_factories={"http": TestModelFactory()})
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
            raise ModelError("busy", "test-secret", retryable=True)
        return {"text": kwargs["user"]}
    cfg = AIConfig(id="ai", provider="custom", models={"one": {"nested": ["original"]}})
    service = AIService(model_factories={"custom": TestModelFactory(responder)})
    result = await service.execute(cfg, "prefix", "body", model="one")
    assert result.text == "prefix\n\nbody"
    assert received[0] == received[1] == cfg.model_dump()
    await service.close()


@pytest.mark.parametrize("failure,retryable,uncertain", [
    (httpx.ConnectTimeout, True, False), (httpx.ConnectError, True, False),
    (httpx.PoolTimeout, True, False), (429, True, False), (408, True, False),
    (httpx.ReadTimeout, False, True), (httpx.WriteError, False, True),
    (httpx.RemoteProtocolError, False, True), (500, True, False),
    (503, True, False), (401, False, False), (403, False, False), (400, False, False),
    (RuntimeError, False, False),
])
async def test_retryable_status_and_transport_failures(monkeypatch, failure, retryable, uncertain):
    monkeypatch.setattr("logagent.ai.service._RETRY_DELAY", 0)
    calls = 0
    async def transport(request):
        nonlocal calls
        calls += 1
        if isinstance(failure, int):
            return httpx.Response(failure, text="test-secret")
        raise failure("test-secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)})
        result = await service.execute(config(), "", "body", model="one")
        assert result.status == "failed"
        assert calls == (6 if retryable else 1)
        assert bool(result.error.details.get("uncertain")) == uncertain
        assert "test-secret" not in result.model_dump_json()
        await service.close()


@pytest.mark.parametrize("body", [
    {}, {"choices": []}, {"choices": [{"message": {"role": "assistant", "content": ""}}]},
    {"choices": [{"message": {"role": "assistant", "content": "yes"}}], "usage": []},
    {"choices": [{"message": {"role": "assistant", "content": "yes"}}], "error": {"key": "test-secret"}},
    {"choices": [{"message": {"role": "assistant", "content": ["bad"]}}]},
])
async def test_malformed_response_is_failure_without_retry(body):
    calls = 0
    def transport(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)})
        result = await service.execute(config(), "", "body", model="one")
        assert result.error.code == "invalid_response" and calls == 1
        assert "test-secret" not in result.model_dump_json()
        await service.close()


async def test_total_timeout_includes_credentials_and_starts_no_request():
    calls = []
    class Credentials:
        async def resolve(self, value):
            await asyncio.Future()
    provider = TestModelFactory(lambda **kwargs: calls.append(kwargs))
    service = AIService(model_factories={"http": provider}, credential_resolver=Credentials())
    result = await service.execute(config(timeout=.02, api_key={"kind": "env", "name": "KEY"}),
                                   "", "body", model="one")
    assert result.status == "timeout" and calls == []
    await service.close()


async def test_total_timeout_includes_retry_backoff():
    calls = []
    def responder(**kwargs):
        calls.append(kwargs)
        raise ModelError("busy", "private", retryable=True)
    service = AIService(model_factories={"http": TestModelFactory(responder)})
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
            raise ModelError("busy", "private", retryable=True)
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            if phase != "swallowed":
                raise
            return {"text": "must not succeed"}
    service = AIService(model_factories={"http": TestModelFactory(responder)})
    task = asyncio.create_task(service.execute(config(), "", "body", model="one"))
    await entered.wait()
    task.cancel()
    result = await task
    assert result.status == "cancelled" and len(calls) == 1
    await service.close()


async def test_missing_credential_resolver_fails_before_provider():
    service = AIService(model_factories={"http": TestModelFactory()})
    result = await service.execute(config(api_key={"kind": "env", "name": "KEY"}),
                                   "", "body", model="one")
    assert result.error.code == "credential_resolver_missing"
    await service.close()


async def test_close_is_bounded_idempotent_and_attempts_all_clients():
    closed = []
    class Client(TestModelFactory):
        def __init__(self, kind):
            self.kind = kind
        async def close(self):
            closed.append(self.kind)
            if self.kind == "hang":
                await asyncio.Future()
            if self.kind == "fail":
                raise OSError("test-secret")
    healthy = Client("ok")
    service = AIService(model_factories={"a": Client("hang"), "b": Client("fail"),
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
    service = AIService(model_factories={"http": TestModelFactory(responder)}, credential_resolver=Credentials())
    result = await service.execute(
        config(timeout=60, api_key={"kind": "env", "name": "KEY"}), "", "body", model="one",
    )
    assert entered.is_set() and result.status == "timeout"
    await service.close()


async def test_owned_http_client_has_no_hidden_short_timeout():
    provider = OpenAIModelFactory()
    assert provider.client.timeout == httpx.Timeout(None)
    await provider.close()
    assert provider.client.is_closed


async def test_unregistered_interfaces_never_fall_back_to_mock():
    service = AIService(model_factories={"http": OpenAIModelFactory()})
    try:
        for name in ("mock", "anthropic", "openai-responses"):
            with pytest.raises(LogAgentError) as error:
                service.validate(AIConfig(id="ai", provider=name, models={"one": {}}))
            assert error.value.code == "provider_missing"
    finally:
        await service.close()


async def test_retry_logs_are_immediate_and_survive_application_formatter(monkeypatch, caplog):
    from logagent.lifecycle.logging import RedactingJsonFormatter
    from logagent.models import ExecutionContext

    monkeypatch.setattr("logagent.ai.service._RETRY_DELAY", 0)
    calls = 0
    async def transport(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="test-secret")
        attempts = [r for r in caplog.records if r.msg == "ai_attempt_failed"]
        assert len(attempts) == 1  # The error must be visible before the next attempt.
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "recovered"}}],
        })
    context = ExecutionContext(workflow_id="workflow", session_id="session")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)})
        result = await service.execute(config(), "secret prompt", "secret input", model="one",
                                       task_id="analysis", context=context)
        await service.close()
    assert result.status == "success" and calls == 2
    records = [r for r in caplog.records if r.msg == "ai_attempt_failed"]
    entry = json.loads(RedactingJsonFormatter().format(records[0]))
    assert {key: entry[key] for key in ("attempt", "will_retry", "status_code", "task_id",
                                       "session_id", "workflow_id")} == {
        "attempt": 1, "will_retry": True, "status_code": 503, "task_id": "analysis",
        "session_id": "session", "workflow_id": "workflow",
    }
    assert "secret" not in json.dumps(entry)


async def test_unconfigured_credentials_never_read_ambient_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret")
    seen = []
    async def transport(request):
        seen.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "local answer"}}],
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)})
        result = await service.execute(config(), "", "body", model="one")
        await service.close()
    assert result.status == "success" and len(seen) == 1
    assert "authorization" not in seen[0].headers


async def test_concurrent_models_share_channel_but_not_parameters_or_messages():
    seen = {}
    both_entered = asyncio.Event()
    async def transport(request):
        payload = json.loads(request.content)
        seen[payload["model"]] = payload
        if len(seen) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), 2)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": payload["model"]}}],
        })
    cfg = config()
    cfg.models = {"one": {"vendor": {"mode": "fast"}}, "two": {"reasoning_effort": "high"}}
    original = cfg.model_dump()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)})
        results = await asyncio.gather(*(
            service.execute(cfg, "{input}", name + " input", model=name) for name in cfg.models
        ))
        await service.close()
    assert [r.text for r in results] == ["one", "two"]
    assert cfg.model_dump() == original
    assert seen["one"]["vendor"] == {"mode": "fast"}
    assert "reasoning_effort" not in seen["one"] and "vendor" not in seen["two"]
    assert seen["two"]["messages"][-1]["content"] == "two input"


@pytest.mark.parametrize("message,code", [
    (AIMessage(content="", additional_kwargs={"refusal": "private"}), "provider_rejected"),
    (AIMessage(content="partial", tool_calls=[{"name": "query", "args": {}, "id": "tool"}]),
     "invalid_response"),
    (AIMessage(content=[{"type": "text", "text": "unsupported block"}]), "invalid_response"),
])
async def test_model_rejection_or_nontext_result_is_not_success(message, code):
    service = AIService(model_factories={"http": TestModelFactory(lambda **kwargs: message)})
    result = await service.execute(config(), "", "body", model="one")
    assert result.status == "failed" and result.error.code == code
    assert "private" not in result.model_dump_json()
    await service.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_real_langchain_request_uses_total_deadline_and_cancellation(cancel):
    entered = asyncio.Event()
    stopped = asyncio.Event()
    calls = 0
    async def transport(request):
        nonlocal calls
        calls += 1
        entered.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        service = AIService(model_factories={"http": OpenAIModelFactory(client)})
        operation = asyncio.create_task(service.execute(
            config(timeout=2 if cancel else .1), "", "body", model="one",
        ))
        await asyncio.wait_for(entered.wait(), 1)
        if cancel:
            operation.cancel()
        result = await operation
        await service.close()
    assert result.status == ("cancelled" if cancel else "timeout")
    assert stopped.is_set() and calls == 1
