"""Verify the benchmark uses production collection, AI and durable workflows."""
import json
from argparse import Namespace

import httpx
import pytest

from evals.longmemeval_prompts import BUSINESS, CHECKPOINT, prompt_fingerprints
from evals.run_longmemeval import (
    RecordedStream,
    evidence_text,
    execute_workflow,
    run,
    workflow_snapshot,
)
from workflowweave.agent.config import AgentConfig
from workflowweave.ai import AIService
from workflowweave.ai.channels import OpenAIChannelFactory
from workflowweave.collection.manager import CollectorManager
from workflowweave.workflow.execution.runner import WorkflowRunner


def test_checkpoint_prompt_reuses_project_default_and_business_rules():
    import hashlib

    assert CHECKPOINT == AgentConfig.model_fields["summary_prompt"].default
    assert BUSINESS.startswith(CHECKPOINT + "\n\n")
    assert "Do not ask for a question" in BUSINESS
    assert "exact names" in BUSINESS and "earlier and later values" in BUSINESS
    assert "max_tokens" not in BUSINESS and "o200k_base" not in BUSINESS
    fingerprints = prompt_fingerprints()
    for line, text in (("B", CHECKPOINT), ("C", BUSINESS)):
        assert fingerprints[line] == hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def case():
    return {"question_id": "q", "question": "SECRET_QUESTION", "answer": "SECRET_ANSWER",
            "question_date": "2024/01/01", "question_type": "multi-session",
            "haystack_dates": ["2023/01/01"], "haystack_session_ids": ["answer_session"],
            "haystack_sessions": [[{"role": "user", "content": "RAW_SENTINEL",
                                    "has_answer": True}]], "answer_session_ids": ["answer_session"]}


def test_evidence_preserves_dates_and_text_without_question_or_labels(case):
    text = evidence_text(case)
    assert "2023/01/01" in text and "RAW_SENTINEL" in text
    assert all(word not in text for word in ["SECRET_QUESTION", "SECRET_ANSWER", "has_answer", "answer_session"])


def test_blind_compression_changes_only_prompt(case, tmp_path):
    source = tmp_path / "evidence.txt"
    source.write_text(evidence_text(case))
    b = workflow_snapshot(case, "B", source, "http://local/v1", 1024, request_timeout=900)
    c = workflow_snapshot(case, "C", source, "http://local/v1", 1024, request_timeout=900)
    assert b.workflow.fan_in == c.workflow.fan_in
    assert b.workflow.analyses[0].user_prompt != c.workflow.analyses[0].user_prompt
    assert b.workflow.analyses[0].user_prompt == CHECKPOINT
    assert c.workflow.analyses[0].user_prompt == BUSINESS
    for snap in (b, c):
        assert snap.workflow.fan_in.order == ["compress"]
        assert snap.workflow.fan_in.single_task_optimization is False
        assert snap.workflow.analysis_failure == "stop"
        assert "SECRET_QUESTION" not in snap.workflow.analyses[0].user_prompt
        assert "o200k_base" not in snap.workflow.analyses[0].user_prompt
    assert b.ai["inspection_ai"].models["gpt-6-luna"] == {
        "max_tokens": 1024, "reasoning_effort": "xhigh", "streaming": True,
    }
    assert b.ai["inspection_ai"].models["gpt-6.1-sol"]["reasoning_effort"] == "medium"
    assert b.ai["inspection_ai"].models["gpt-6.1-sol"]["streaming"] is True
    assert b.ai["inspection_ai"].timeout == 900


async def test_tokenizer_failure_stops_before_data_or_paid_calls(monkeypatch, tmp_path):
    import tiktoken

    def unavailable(name):
        raise RuntimeError("tokenizer unavailable")

    monkeypatch.setenv("WORKFLOWWEAVE_INSPECTION_API_KEY", "unit-test")
    monkeypatch.setattr(tiktoken, "get_encoding", unavailable)
    with pytest.raises(RuntimeError, match="tokenizer unavailable"):
        await run(Namespace(output=tmp_path / "must-not-exist"))
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize("compression_fails", [False, True])
@pytest.mark.parametrize("line", ["B", "C"])
async def test_real_workflow_archives_cli_and_isolates_summary(case, tmp_path, compression_fails, line):
    seen = []
    async def transport(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body["stream"] is True
        assert "streaming" not in body
        assert body["stream_options"] == {"include_usage": True}
        if compression_fails and body["model"] == "gpt-6-luna":
            return httpx.Response(403, json={"error": {"message": "quota", "type": "quota"}})
        text = "SUMMARY_SENTINEL" if body["model"] == "gpt-6-luna" else "FINAL_ANSWER"
        payload = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1,
                   "model": body["model"], "choices": [{"index": 0,
                   "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
        final = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1,
                 "model": body["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
        content = f"data: {json.dumps(payload)}\n\ndata: {json.dumps(final)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=content.encode(), headers={"content-type": "text/event-stream"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        ai = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory(client)})
        runner = WorkflowRunner(CollectorManager(None), ai, None, database=tmp_path / "workflow.sqlite3")
        try:
            result = await execute_workflow(runner, case, line, tmp_path, "http://local/v1", 1024, authenticated=False)
            assert result.collection[0].status == "success"
            assert "RAW_SENTINEL" in result.collection[0].raw["stdout"]
            if compression_fails:
                assert len(seen) == 1 and result.status == "failed"
                assert result.aggregate is None
            else:
                assert result.status == "completed"
                assert "RAW_SENTINEL" in json.dumps(seen[0])
                assert "SECRET_QUESTION" not in json.dumps(seen[0])
                assert "SECRET_ANSWER" not in json.dumps(seen[0])
                assert seen[0]["messages"][-1]["content"] == (CHECKPOINT if line == "B" else BUSINESS)
                assert "SUMMARY_SENTINEL" in json.dumps(seen[1])
                assert "RAW_SENTINEL" not in json.dumps(seen[1])
                assert "SECRET_QUESTION" in json.dumps(seen[1])
                assert result.outputs["final"] == "FINAL_ANSWER"
                assert result.analyses[0].usage["input_tokens"] == 10
            assert await runner.history(result.session_id)
        finally:
            await runner.shutdown()
            await ai.close()


async def test_sse_recorder_is_incremental_and_keeps_usage():
    consumed, saved = [], []

    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in (b'data: {"id":"r","choices":[]}\n\n',
                         b'data: {"id":"r","choices":[],"usage":{"total_tokens":13}}\n\n',
                         b'data: [DONE]\n\n'):
                consumed.append(part)
                yield part

    record = {"status": "failed"}
    iterator = RecordedStream(Bytes(), record, saved.append).__aiter__()
    first = await anext(iterator)
    assert first == consumed[0] and len(consumed) == 1
    assert saved == []
    async for _ in iterator:
        pass
    assert record["status"] == "success"
    assert record["usage"]["total_tokens"] == 13
    assert saved == [record]


async def test_sse_recorder_rejects_truncated_stream():
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"id":"r","choices":[]}\n\n'

    saved = []
    with pytest.raises(ValueError, match="without"):
        async for _ in RecordedStream(Bytes(), {"status": "failed"}, saved.append):
            pass
    assert saved[0]["status"] == "failed"


async def test_sse_recorder_keeps_success_when_sdk_closes_after_done():
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: [DONE]\n\n'

    saved = []
    iterator = RecordedStream(Bytes(), {"status": "failed"}, saved.append).__aiter__()
    await anext(iterator)
    await iterator.aclose()
    assert saved[0]["status"] == "success"
