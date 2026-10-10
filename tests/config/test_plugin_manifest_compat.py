"""QwenPaw/WorkFLowWeave plugin manifest compatibility contracts."""

from __future__ import annotations

import pytest

from workflowweave.config.manifest import (
    normalize_plugin_manifest,
)
from workflowweave.errors import WorkFLowWeaveError


def test_workflowweave_v1_manifest_is_normalized_without_losing_kind():
    manifest = normalize_plugin_manifest(
        {
            "id": "example",
            "version": "1.2.3",
            "kind": "channel",
            "api_version": 1,
            "entry": {"backend": "main.py"},
        },
        directory_name="example",
    )

    assert manifest.id == "example"
    assert manifest.display_name == "example"
    assert manifest.kind == "channel"
    assert manifest.entry_backend == "main.py"
    assert manifest.source_format == "workflowweave-v1"


def test_qwenpaw_manifest_preserves_display_metadata_and_dependencies():
    manifest = normalize_plugin_manifest(
        {
            "id": "qwenpaw-memos",
            "name": "QwenPaw Memos",
            "version": "1.0.0",
            "type": "channel",
            "entry": {"backend": "plugin.py"},
            "dependencies": ["httpx>=0.27"],
            "qwenpaw_version": {"min": "1.1.6", "max": "2.1.0"},
            "meta": {"source": "memos"},
        },
        directory_name="qwenpaw-memos",
    )

    assert manifest.kind == "channel"
    assert manifest.display_name == "QwenPaw Memos"
    assert manifest.source_format == "qwenpaw"
    assert manifest.dependencies == ("httpx>=0.27",)
    assert manifest.metadata["source"] == "memos"


@pytest.mark.parametrize(
    "manifest",
    [
        {
            "id": "bad",
            "version": "1",
            "kind": "tool",
            "type": "channel",
            "api_version": 1,
            "entry": {"backend": "main.py"},
        },
        {
            "id": "bad",
            "name": "Bad",
            "version": "1",
            "type": "channel",
            "entry": {"backend": "../main.py"},
        },
        {
            "id": "bad",
            "name": "Bad",
            "version": "1",
            "type": "channel",
            "entry": {"backend": "/tmp/main.py"},
        },
        {
            "id": "bad",
            "name": "Bad",
            "version": "1",
            "type": "unknown",
            "entry": {"backend": "main.py"},
        },
    ],
)
def test_conflicting_or_unsafe_manifest_is_rejected(manifest):
    with pytest.raises(WorkFLowWeaveError) as error:
        normalize_plugin_manifest(manifest, directory_name="bad")

    assert error.value.code == "plugin_manifest_invalid"
