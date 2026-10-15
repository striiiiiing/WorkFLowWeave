"""Exercise the production serializer/token-budget implementation unchanged."""

import json
from datetime import UTC, datetime

from workflowweave.models import (
    AIConfig,
    CollectionResult,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)
from workflowweave.workflow.input_processing import process_input

CONDITIONS = {
    "json_full": ("none", False, False),
    "zon_full": ("zon", False, False),
    "ison_full": ("ison", False, False),
    "json_summary": ("none", False, True),
    "zon_summary": ("zon", False, True),
    "ison_summary": ("ison", False, True),
}
FIELD_TOKENS = 96


def prepare(case: dict, condition: str) -> dict:
    format, limited, summarized = CONDITIONS[condition]
    ai = AIConfig(id="eval", provider="openai_compatible_api", base_url="http://127.0.0.1:19026/v1",
                  models={"gpt-6-luna": {}, "gpt-6.1-sol": {}})
    sources = {key: SourceConfig(id=key, call={"kind": "cli", "mode": "argv", "executable": "python"},
                                 limits={"field_tokens": FIELD_TOKENS if limited else None,
                                         "item_tokens": None})
               for key in case["sources"] if case["sources"][key]}
    analyses = [{"id": "analyze", "ai": "eval", "model": "gpt-6.1-sol", "user_prompt": case["task"]}]
    fan_in = None
    if summarized:
        analyses = [{"id": "compress", "ai": "eval", "model": "gpt-6-luna", "user_prompt": case["task"]}]
        fan_in = {
            "order": ["compress"],
            "single_task_optimization": False,
            "ai": "eval",
            "model": "gpt-6.1-sol",
            "reuse_from": None,
            "user_prompt": "基于压缩任务的事实简报输出最终巡检报告。",
        }
    workflow = WorkflowDefinition(id="eval", sources=list(sources), analyses=analyses, fan_in=fan_in,
        input_processing={"format": format, "total_tokens": None})
    snapshot = WorkflowSnapshot(workflow=workflow, sources=sources, ai={"eval": ai}, channels={},
                                created_at=datetime.now(UTC))
    results = [CollectionResult(source_id=key, status="success",
                raw={"stdout": json.dumps(case["sources"][key], ensure_ascii=False)}) for key in sources]
    # All limits are intentionally disabled for this experiment. Let the
    # production processor pass the full structured input without a guessed
    # tokenizer for the new model names.
    text, views = process_input(snapshot, results, ())
    failed = [view for view in views if view.status == "failed"]
    if failed:
        raise ValueError([view.model_dump(mode="json") for view in failed])
    return {"text": text, "characters": len(text),
            "views": [view.model_dump(mode="json") for view in views], "summarized": summarized,
            "workflow": workflow.model_dump(mode="json")}
