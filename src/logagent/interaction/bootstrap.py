"""Lightweight console entry point that can report progress before CLI imports."""

from __future__ import annotations

import sys


def main() -> None:
    arguments = sys.argv[1:]
    if arguments[:1] == ["start"] and "--help" not in arguments and "-h" not in arguments:
        print("[后端启动] 正在加载命令行模块...", file=sys.stderr, flush=True)
    from .cli import main as cli_main

    cli_main()
