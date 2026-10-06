"""Run one CLI source through the collection manager without an API server."""

from __future__ import annotations

import argparse
import asyncio

from workflowweave.collection import CollectorManager
from workflowweave.models import CollectionContext, SourceConfig


async def run(executable: str, argv: list[str]) -> int:
    source = SourceConfig(
        id="example_source",
        call={"kind": "cli", "mode": "argv", "executable": executable, "argv": argv},
    )
    result = await CollectorManager(None).collect(
        source,
        CollectionContext(workflow_id="example", session_id="example-run"),
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status in {"success", "empty"} else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="独立运行一个 CLI 数据源")
    parser.add_argument("executable", nargs="?", default="uname")
    parser.add_argument("argv", nargs="*", default=["-a"])
    args = parser.parse_args()
    return asyncio.run(run(args.executable, args.argv))


if __name__ == "__main__":
    raise SystemExit(main())
