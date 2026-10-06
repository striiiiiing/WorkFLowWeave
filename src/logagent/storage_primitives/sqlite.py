"""Explicit SQLite connection configuration and transaction boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


def configure_connection(
    connection,
    *,
    busy_timeout_ms: int,
    foreign_keys: bool = True,
    journal_mode: str | None = None,
    synchronous: str | None = None,
) -> None:
    if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be a non-negative integer")
    cursor = connection.cursor()
    try:
        if journal_mode is not None:
            cursor.execute(f"PRAGMA journal_mode={_pragma_value(journal_mode)}")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cursor.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
        if synchronous is not None:
            cursor.execute(f"PRAGMA synchronous={_pragma_value(synchronous)}")
    finally:
        cursor.close()


def _pragma_value(value: str) -> str:
    normalized = value.upper()
    if not normalized.isidentifier():
        raise ValueError("invalid SQLite PRAGMA value")
    return normalized


@contextmanager
def transaction(connection, *, immediate: bool = False) -> Iterator[object]:
    """Commit one explicit transaction or roll it back without hiding errors."""
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
