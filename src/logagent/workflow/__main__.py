"""Read-only session and stage inspection: ``python -m logagent.workflow``."""

from __future__ import annotations

import argparse
import json
import sys

from logagent.errors import LogAgentError
from logagent.workflow.store import SQLiteRunStore

_STAGES = ("collect", "analyze", "aggregate", "notify", "finish")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读查看 SQLite 中的 Workflow 运行与阶段历史")
    parser.add_argument("--database", default="data/workflows.sqlite3", help="SQLite 数据库路径")
    commands = parser.add_subparsers(dest="command", required=True)
    sessions = commands.add_parser("sessions", help="列出 Workflow sessions")
    sessions.add_argument("--workflow-id", help="按 Workflow ID 筛选")
    sessions.add_argument("--limit", type=int, default=50)
    sessions.add_argument("--offset", type=int, default=0)
    show = commands.add_parser("show", help="查看 session、配置快照和已保存阶段结果")
    show.add_argument("session_id")
    history = commands.add_parser("history", help="按时间顺序查看各阶段的输入、输出与事件")
    history.add_argument("session_id")
    history.add_argument("--stage", help="按阶段筛选，例如 collect、analyze、notify")
    history.add_argument("--limit", type=int, default=100)
    history.add_argument("--offset", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with SQLiteRunStore(args.database, read_only=True) as store:
            if args.command == "sessions":
                output = store.list_sessions(args.workflow_id, limit=args.limit, offset=args.offset)
            elif args.command == "history":
                output = store.history(
                    args.session_id, stage=args.stage, limit=args.limit, offset=args.offset
                )
            else:
                store.verify_session(args.session_id)
                output = store.get_session(args.session_id)
                output["stages"] = {
                    stage: result
                    for stage in _STAGES
                    if (result := store.stage_result(args.session_id, stage)) is not None
                }
                output["collections"] = store.item_results(args.session_id, "collect")
                output["analyses"] = store.item_results(args.session_id, "analyze")
                output["aggregate"] = store.item_results(args.session_id, "aggregate")
                output["deliveries"] = store.delivery_results(args.session_id)
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except LogAgentError as exc:
        print(
            json.dumps({"error": exc.info.model_dump(mode="json")}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
