from pathlib import Path

import pytest

from workflowweave.storage_primitives.atomic import atomic_write_bytes, atomic_write_json


def test_atomic_write_publishes_complete_file_and_json(tmp_path: Path):
    target = tmp_path / "nested" / "value.json"
    atomic_write_json(target, {"b": 2, "a": "值"}, sort_keys=True)
    assert target.read_text(encoding="utf-8") == '{"a":"值","b":2}'
    assert target.stat().st_mode & 0o777 == 0o600

    atomic_write_bytes(target, b"replacement")
    assert target.read_bytes() == b"replacement"


def test_atomic_write_keeps_old_value_and_cleans_temp_if_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "value"
    target.write_bytes(b"old")

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr("workflowweave.storage_primitives.atomic.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_bytes(target, b"new")

    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_json_rejects_non_json_number(tmp_path):
    with pytest.raises(ValueError, match="Out of range"):
        atomic_write_json(tmp_path / "value", {"number": float("nan")})
