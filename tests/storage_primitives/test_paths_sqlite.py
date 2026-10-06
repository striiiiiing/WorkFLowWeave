import sqlite3

import pytest

from workflowweave.storage_primitives.paths import StoragePathError, resolve_under, temporary_path
from workflowweave.storage_primitives.sqlite import configure_connection, transaction


def test_resolve_under_blocks_absolute_and_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    assert resolve_under(root, "safe/file") == root / "safe" / "file"
    with pytest.raises(StoragePathError):
        resolve_under(root, "../outside/file")
    with pytest.raises(StoragePathError):
        resolve_under(root, "link/file")
    with pytest.raises(StoragePathError):
        resolve_under(root, outside / "file")


def test_temporary_path_is_unique_and_created(tmp_path):
    first = temporary_path(tmp_path / "nested", prefix=".store-")
    second = temporary_path(tmp_path / "nested", prefix=".store-")
    assert first != second
    assert first.is_file() and second.is_file()


def test_sqlite_configuration_and_transaction_rollback():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    configure_connection(
        connection,
        busy_timeout_ms=321,
        foreign_keys=True,
        journal_mode="MEMORY",
        synchronous="FULL",
    )
    assert connection.execute("PRAGMA busy_timeout").fetchone() == (321,)
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    connection.execute("CREATE TABLE values_table (value INTEGER)")

    with pytest.raises(RuntimeError, match="rollback"):
        with transaction(connection, immediate=True):
            connection.execute("INSERT INTO values_table VALUES (1)")
            raise RuntimeError("rollback")

    assert connection.execute("SELECT value FROM values_table").fetchall() == []


def test_sqlite_pragma_input_is_validated_before_execution():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    with pytest.raises(ValueError, match="invalid SQLite PRAGMA"):
        configure_connection(
            connection,
            busy_timeout_ms=1,
            journal_mode="WAL; DROP TABLE users",
        )
