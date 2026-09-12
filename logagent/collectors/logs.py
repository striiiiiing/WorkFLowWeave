"""Bounded reads of complete UTF-8 lines from the application's log file."""

import os
import stat
from pathlib import Path

from logagent._io import run_io
from logagent.errors import LogAgentError
from logagent.models import Model, PositiveInt

from .base import BaseCollector, CollectionContext
from .setters import CommonSetters


class LogsOptions(Model):
    max_bytes: PositiveInt = 65536
    max_lines: PositiveInt = 200


def _not_regular() -> LogAgentError:
    return LogAgentError(
        "COLLECTOR_FAILED", "The tool log must be a regular file", {"reason": "not_regular_file"}
    )


def _read_tail(path: Path, max_bytes: int, max_lines: int) -> list[dict]:
    try:
        # Check before open as well as after it: a FIFO must never block opening,
        # including when rotation changes the path between these two operations.
        if not stat.S_ISREG(path.stat().st_mode):
            raise _not_regular()
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise _not_regular()
            size = info.st_size
            start = max(0, size - max_bytes)
            starts_at_line = start == 0
            if start:
                # The extra byte is only a boundary probe, never output content.
                stream.seek(start - 1)
                starts_at_line = stream.read(1) == b"\n"
            stream.seek(start)
            data = stream.read(size - start)
        if not starts_at_line:
            data = data.partition(b"\n")[2]
        data = data[: data.rfind(b"\n") + 1]
        lines = data.split(b"\n")[:-1][-max_lines:]
        return [
            {"line": index, "text": line.removesuffix(b"\r").decode("utf-8")}
            for index, line in enumerate(lines, start=1)
        ]
    except FileNotFoundError as exc:
        raise LogAgentError("COLLECTOR_MISSING", "The tool log does not exist", {"reason": "missing"}) from exc
    except PermissionError as exc:
        raise LogAgentError(
            "COLLECTOR_FAILED", "The tool log is not readable", {"reason": "permission_denied"}
        ) from exc
    except OSError as exc:
        raise LogAgentError(
            "COLLECTOR_FAILED", "The tool log could not be read", {"reason": "read_failed"}
        ) from exc
    except UnicodeError as exc:
        raise LogAgentError(
            "COLLECTOR_FAILED", "The selected log lines are not valid UTF-8", {"reason": "invalid_utf8"}
        ) from exc


class LogsCollector(BaseCollector):
    name = "logs"
    description = "Collect complete lines from a bounded tail of the tool log."
    options_model = LogsOptions
    setters_model = CommonSetters
    fields = ("line", "text")

    async def collect(
        self, options: LogsOptions, setters: CommonSetters, context: CollectionContext
    ) -> list[dict]:
        if context.log_path is None:
            raise LogAgentError(
                "COLLECTOR_MISSING", "No tool log is configured", {"reason": "not_configured"}
            )
        return await run_io(_read_tail, Path(context.log_path), options.max_bytes, options.max_lines)
