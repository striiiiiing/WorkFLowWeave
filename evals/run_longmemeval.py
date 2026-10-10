"""Paid LongMemEval A/B/C evaluation with an auditable shuffled sample."""

import argparse
import asyncio
import hashlib
import json
import os
import random
from datetime import UTC, datetime
from pathlib import Path

import httpx

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    AIConfig,
    EnvironmentCredential,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)

from .longmemeval_official import get_anscheck_prompt
from .longmemeval_prompts import BUSINESS, CHECKPOINT, prompt_fingerprints, prompt_manifest
from .longmemeval_reuse import reuse_completed

ANALYSIS = "Answer the question using only the provided history. Give the answer directly and briefly."
TOKENIZER_NAME = "o200k_base"
TOKENIZER_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
TOKENIZER_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
AI_ID = "inspection_ai"
CREDENTIAL_ENV = "WORKFLOWWEAVE_INSPECTION_API_KEY"


class RecordedStream(httpx.AsyncByteStream):
    """Observe SSE bytes as LangChain consumes them without buffering the response."""

    def __init__(self, stream, record, save):
        self.stream, self.record, self.save = stream, record, save

    async def __aiter__(self):
        buffer = b""
        done = False
        try:
            async for chunk in self.stream:
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        done = True
                        self.record["status"] = "success"
                        continue
                    payload = json.loads(data)
                    if payload.get("error"):
                        raise ValueError(f"SSE provider error: {payload['error']}")
                    if payload.get("id"):
                        self.record["response_id"] = payload["id"]
                    if payload.get("model"):
                        self.record["response_model"] = payload["model"]
                    if payload.get("usage"):
                        self.record["usage"] = payload["usage"]
                    for choice in payload.get("choices", []):
                        if choice.get("finish_reason"):
                            self.record["finish_reason"] = choice["finish_reason"]
                yield chunk
            if not done:
                raise ValueError("SSE stream ended without [DONE]")
            self.record["status"] = "success"
        finally:
            self.record["finished_at"] = datetime.now(UTC).isoformat()
            self.save(self.record)

    async def aclose(self):
        await self.stream.aclose()


def evidence_text(entry):
    """Serialize only the blind evidence presented to the compression task."""
    sessions = []
    for date, session in zip(entry["haystack_dates"], entry["haystack_sessions"], strict=True):
        turns = [{"role": turn["role"], "content": turn["content"]} for turn in session]
        sessions.append({"date": date, "turns": turns})
    return json.dumps({"history": sessions}, ensure_ascii=False)


def workflow_snapshot(entry, line, evidence_path, base_url, max_tokens, request_timeout=900):
    """Construct a production WorkflowSnapshot for one LongMemEval route."""
    if line not in {"A", "B", "C"}:
        raise ValueError("line must be A, B or C")
    compression_prompt = CHECKPOINT if line == "B" else BUSINESS
    question = f"Current Date: {entry['question_date']}\nQuestion: {entry['question']}\n{ANALYSIS}"
    task_prompt = question if line == "A" else compression_prompt
    analyses = [{"id": "compress" if line != "A" else "analyze", "ai": AI_ID,
                 "model": "gpt-6-luna" if line != "A" else "gpt-6.1-sol",
                 "user_prompt": task_prompt}]
    fan_in = None if line == "A" else {"order": ["compress"], "single_task_optimization": False,
        "ai": AI_ID, "model": "gpt-6.1-sol", "reuse_from": None,
        "user_prompt": question}
    workflow = WorkflowDefinition(id="longmemeval", sources=["history"], analyses=analyses,
        fan_in=fan_in, system_prompt="Answer from the provided history; distinguish evidence from guesses.", input_prompt="{input}", analysis_failure="stop", send_partial=False,
        input_processing={"format": "none", "total_tokens": None})
    source = SourceConfig(id="history", call={"kind": "cli", "mode": "argv", "executable": "/bin/cat",
        "argv": [str(evidence_path)]})
    ai = AIConfig(id=AI_ID, provider="openai_compatible_api", base_url=base_url,
                  models={"gpt-6-luna": {"max_tokens": max_tokens, "reasoning_effort": "xhigh", "streaming": True},
                          "gpt-6.1-sol": {"max_completion_tokens": 4096, "reasoning_effort": "medium", "streaming": True}},
                  retries=0, timeout=request_timeout)
    return WorkflowSnapshot(workflow=workflow, sources={"history": source}, ai={AI_ID: ai},
                            channels={}, created_at=datetime.now(UTC))


async def execute_workflow(runner, entry, line, workdir, base_url, max_tokens,
                           request_timeout=900, authenticated=True):
    evidence = Path(workdir) / f"{entry['question_id']}-{line}.evidence.json"
    evidence.write_text(evidence_text(entry), encoding="utf-8")
    snapshot = workflow_snapshot(entry, line, evidence, base_url, max_tokens, request_timeout)
    if authenticated:
        snapshot.ai[AI_ID].api_key = EnvironmentCredential(name=CREDENTIAL_ENV)
    (Path(workdir) / f"{entry['question_id']}-{line}.snapshot.json").write_text(snapshot.model_dump_json(indent=2))
    result = await runner.trigger(snapshot)
    return await runner.wait(result)


def history_text(entry):
    return json.dumps({"history": entry["haystack_sessions"], "question_date": entry["question_date"],
                       "question": entry["question"]}, ensure_ascii=False)


def shuffled_entries(path, seed):
    entries = json.loads(path.read_text())
    rng = random.Random(seed)
    rng.shuffle(entries)
    return entries


def select_entries(path, start, end, seed, holdout_size=100):
    entries = shuffled_entries(path, seed)
    if start <= holdout_size:
        raise ValueError("pilot range overlaps the reserved first 100 shuffled entries")
    selected = entries[start - 1:end]
    if len(selected) != end - start + 1:
        raise ValueError("requested shuffled ordinal range is outside dataset")
    return selected


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def run(args):
    from contextvars import ContextVar

    import tiktoken
    from langchain_core.messages import HumanMessage

    from workflowweave.ai import AIService
    from workflowweave.ai.channels import OpenAIChannelFactory
    from workflowweave.ai.service import stream_message
    from workflowweave.collection.manager import CollectorManager
    from workflowweave.config.credentials import CredentialManager
    from workflowweave.models import SystemConfig
    from workflowweave.workflow.execution.runner import WorkflowRunner

    if not os.environ.get(CREDENTIAL_ENV):
        raise ValueError(f"{CREDENTIAL_ENV} is required")
    token_counter = tiktoken.get_encoding(TOKENIZER_NAME)

    def count(text):
        return len(token_counter.encode(text, disallowed_special=()))

    canonical = shuffled_entries(args.order_dataset, args.seed)
    original_ordinals = {entry["question_id"]: n for n, entry in
                         enumerate(json.loads(args.order_dataset.read_text()), start=1)}
    holdout_ids = [e["question_id"] for e in canonical[:100]]
    if args.start <= 100 or args.end < args.start or args.end > len(canonical):
        raise ValueError("pilot must use shuffled ordinals 101..500")
    by_id = {e["question_id"]: e for e in json.loads(args.dataset.read_text())}
    selected_ids = [e["question_id"] for e in canonical[args.start - 1:args.end]]
    entries = [by_id[qid] for qid in selected_ids]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "compression-prompts.json", prompt_manifest())
    split = {"seed": args.seed, "holdout_ids": holdout_ids,
        "order_dataset_sha256": hashlib.sha256(args.order_dataset.read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "shuffled_mapping": [{"shuffled_ordinal": n + 1, "original_ordinal": original_ordinals[e["question_id"]],
                              "question_id": e["question_id"]} for n, e in enumerate(canonical)],
        "selected": [{"shuffled_ordinal": n, "question_id": qid} for n, qid in zip(range(args.start, args.end + 1), selected_ids, strict=True)]}
    write_json(output / "split.json", split)
    current_call = ContextVar("evaluation_call")
    pending = {}
    records = []
    reports, judgments = [], []
    if getattr(args, "reuse", None):
        expected = {}
        for entry in entries:
            for line in "ABC":
                evidence = output / f"{entry['question_id']}-{line}.evidence.json"
                text = evidence_text(entry)
                evidence.write_text(text, encoding="utf-8")
                snapshot = workflow_snapshot(entry, line, evidence, args.base_url,
                                             count(text) // 8, args.request_timeout)
                snapshot.ai[AI_ID].api_key = EnvironmentCredential(name=CREDENTIAL_ENV)
                expected[(entry["question_id"], line)] = snapshot.model_dump(mode="json")
        reports, judgments, records, provenance = reuse_completed(
            args.reuse.resolve(), output, split, prompt_manifest(), expected,
        )
        write_json(output / "reuse.json", provenance)
        write_json(output / "reports.json", reports)
        write_json(output / "judgments.json", judgments)
        (output / "requests.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        print(json.dumps({"event": "routes_reused", "count": len(reports)}), flush=True)
    completed = {(r["question_id"], r["line"]) for r in reports}

    async def request_hook(request):
        if not request.url.path.endswith("chat/completions"):
            return
        body = json.loads(request.content)
        base_call_id = current_call.get()
        stage = "compress" if body["model"] == "gpt-6-luna" else "analysis"
        call_id = base_call_id if base_call_id.endswith("/judge") else f"{base_call_id}/{stage}"
        record = {"call_id": call_id, "configured_model": body["model"],
                  "request_body": body, "started_at": datetime.now(UTC).isoformat(), "status": "failed"}
        records.append(record)
        pending[id(request)] = record
        write_json(output / "request-intents.json", records)

    def save_request(record):
        with (output / "requests.jsonl").open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps({"call_id": record["call_id"], "http_status": record["http_status"],
                          "status": record["status"]}), flush=True)

    async def response_hook(response):
        record = pending.pop(id(response.request))
        record.update(http_status=response.status_code, trace_id=response.headers.get("Ah-Request-Id"))
        if response.is_success:
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise ValueError("streaming request did not return SSE")
            response.stream = RecordedStream(response.stream, record, save_request)
            return
        await response.aread()
        record.update(finished_at=datetime.now(UTC).isoformat(), error_body=response.text)
        save_request(record)

    creds = CredentialManager(SystemConfig(data_dir=str(output)))
    failed = False
    async with httpx.AsyncClient(trust_env=False, timeout=None,
            event_hooks={"request": [request_hook], "response": [response_hook]}) as client:
        ai = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory(client)}, credential_resolver=creds)
        runner = WorkflowRunner(CollectorManager(None), ai, None, database=output / "workflows.sqlite3")
        try:
            for entry in entries:
                text = evidence_text(entry)
                original_tokens = count(text)
                budget = max(1, original_tokens // args.compression_ratio)
                for line in ("A", "B", "C"):
                    if (entry["question_id"], line) in completed:
                        continue
                    current_call.set(f"{entry['question_id']}/{line}/business")
                    result = await execute_workflow(
                        runner, entry, line, output, args.base_url, budget, args.request_timeout,
                    )
                    write_json(output / f"{entry['question_id']}-{line}.result.json", result.model_dump(mode="json"))
                    write_json(output / f"{entry['question_id']}-{line}.history.json", await runner.history(result.session_id))
                    summary = result.analyses[0].text if line != "A" else None
                    ratio = original_tokens / count(summary) if summary else None
                    row = {"question_id": entry["question_id"], "line": line,
                           "session_id": result.session_id, "status": result.status,
                           "original_text_tokens": original_tokens, "text_budget": budget,
                           "compression_ratio": ratio, "compression_budget_met": ratio >= 8 if ratio else None,
                           "answer": next(iter(result.outputs.values()), "")}
                    reports.append(row)
                    write_json(output / "reports.json", reports)
                    await asyncio.sleep(args.interval)
                    if result.status != "completed" or not row["answer"]:
                        failed = True
                        break
                    prompt = get_anscheck_prompt(entry["question_type"], entry["question"], entry["answer"], row["answer"],
                                                 abstention=entry["question_id"].endswith("_abs"))
                    config = AIConfig(id="judge", provider="openai_compatible_api", base_url=args.base_url,
                        api_key=EnvironmentCredential(name=CREDENTIAL_ENV), timeout=args.request_timeout, retries=0,
                        models={"gpt-6-luna": {"reasoning_effort": "max", "max_completion_tokens": 4096, "streaming": True}})
                    current_call.set(f"{entry['question_id']}/{line}/judge")
                    try:
                        async with ai.lease(config, model="gpt-6-luna", streaming=True) as chat:
                            async with asyncio.timeout(args.request_timeout):
                                message = await stream_message(chat, [HumanMessage(content=prompt)], temperature=0)
                        label = message.content.strip().lower()
                        if label not in {"yes", "no"}:
                            raise ValueError("official judge returned invalid label")
                        judgments.append({"question_id": entry["question_id"], "line": line, "status": "success", "correct": label == "yes"})
                    except (ValueError, TimeoutError, WorkFLowWeaveError, httpx.HTTPError) as error:
                        judgments.append({"question_id": entry["question_id"], "line": line, "status": "failed", "error": str(error)})
                        failed = True
                    write_json(output / "judgments.json", judgments)
                    await asyncio.sleep(args.interval)
                    if failed:
                        break
                if failed:
                    break
        finally:
            await runner.shutdown()
            await ai.close()
    complete = len(reports) == len(entries) * 3 and all(r["status"] == "completed" for r in reports) and len(judgments) == len(reports) and all(j["status"] == "success" for j in judgments)
    write_json(output / "run.json", {"status": "complete" if complete else "partial", "project_execution": True,
        "ai_resource": AI_ID, "request_timeout": args.request_timeout, "request_interval": args.interval,
        "compression_effort": "xhigh", "analysis_effort": "medium", "streaming": True,
        "stream_chunk_timeout": None, "reused_from": str(args.reuse) if getattr(args, "reuse", None) else None,
        "compression_prompts": prompt_fingerprints(),
        "candidate_count": len(reports), "actual_requests": len(records), "judge_model": "gpt-6-luna", "judge_effort": "max",
        "judge_temperature": 0, "compression_ratio_target": 8, "token_count_basis": TOKENIZER_NAME,
        "tokenizer": {"encoding": TOKENIZER_NAME, "tiktoken_version": tiktoken.__version__,
                      "url": TOKENIZER_URL, "sha256": TOKENIZER_SHA256},
        "official_scorer_commit": "9e0b455f4ef0e2ab8f2e582289761153549043fc",
        "holdout_executed": False, "judge_bias": "same-family judge selected by user"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evals/data/longmemeval/longmemeval_s_cleaned.json"))
    parser.add_argument("--order-dataset", type=Path, default=Path("evals/data/longmemeval/longmemeval_oracle.json"))
    parser.add_argument("--start", type=int, default=101)
    parser.add_argument("--end", type=int, default=101)
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--compression-ratio", type=int, choices=[8], default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse", type=Path, help="explicitly reuse only completed, scored routes from an identical partial run")
    parser.add_argument("--base-url", default=os.environ.get("EVAL_BASE_URL"))
    parser.add_argument("--interval", type=float, default=12)
    parser.add_argument("--request-timeout", type=float, default=900,
                        help="per-model and judge timeout in seconds")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
