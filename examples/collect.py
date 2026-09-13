"""Run one Collector without a Workflow, model service, API server, or channel."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from logagent.archive import FileArchiveReader
from logagent.collection import CollectorManager
from logagent.config import PluginRegistry, expand_source
from logagent.errors import LogAgentError, validation_error
from logagent.models import CollectionContext, ErrorResponse, SourceConfig, SystemConfig


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立运行 LogAgent 内置采集器")
    parser.add_argument("--collector", choices=["mock", "logs", "history"], default="mock")
    parser.add_argument("--plugin-dir", type=Path, default=Path("plugins"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--max-lines", type=int, default=200)
    parser.add_argument("--history-workflow")
    parser.add_argument("--artifact", choices=["collection", "analysis", "final"], default="final")
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.collector == "history" and args.history_workflow is None:
        parser.error("history 需要 --history-workflow 指定既有 Workflow")
    return args


async def run(args: argparse.Namespace) -> int:
    registry = PluginRegistry()
    report = await registry.discover_plugins(
        SystemConfig(plugin_dir=str(args.plugin_dir.resolve()))
    )
    for error in report.errors:
        print(ErrorResponse(error=error).model_dump_json(), file=sys.stderr)
    manager = CollectorManager(registry.collectorRegister)
    options = {}
    if args.collector == "logs":
        options = {"max_lines": args.max_lines}
    elif args.collector == "history":
        options = {"workflow_id": args.history_workflow, "artifact": args.artifact}
        if args.token_budget is not None:
            options["token_budget"] = args.token_budget
    source = expand_source(
        SourceConfig(
            id="example_source", collector=args.collector, options=options, timeout=args.timeout
        ),
        collector=registry.collectorRegister.get(args.collector),
        options_defaults=registry.collectorRegister.options_defaults(args.collector),
    )
    manager.validate(source)
    result = await manager.collect(
        source,
        CollectionContext(
            workflow_id="example",
            session_id="example_" + uuid4().hex,
            archive=FileArchiveReader(args.data_dir.resolve()),
            log_path=str(args.log_file.resolve()) if args.log_file else None,
        ),
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status in {"success", "empty", "filtered_empty"} else 1


def main() -> int:
    try:
        return asyncio.run(run(arguments()))
    except ValidationError as exc:
        print(ErrorResponse(error=validation_error(exc).info).model_dump_json(), file=sys.stderr)
        return 2
    except LogAgentError as exc:
        print(ErrorResponse(error=exc.info).model_dump_json(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
