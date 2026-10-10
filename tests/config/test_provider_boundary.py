"""Provider aliases are converted once when reading persisted resources or runs."""

from copy import deepcopy

import orjson
import pytest

from tests.workflow.helpers import snapshot
from workflowweave.ai.channels import OpenAIChannelFactory
from workflowweave.ai.options import OPENAI_COMPATIBLE_PROVIDER, validate_config
from workflowweave.config import ResourceStore
from workflowweave.config.migrations import migrate_legacy_snapshot, migrate_resources
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig, WorkflowSnapshot


@pytest.mark.parametrize("version", [3, 4])
def test_stored_alias_is_rewritten_without_mutating_input(tmp_path, version):
    store = ResourceStore(tmp_path / "resources.json")
    data = orjson.loads((tmp_path / "resources.json").read_bytes())
    data["format_version"] = version
    data["ai"]["provider"] = {
        "id": "provider", "provider": "http", "base_url": "http://provider.test/v1",
    }
    original = deepcopy(data)
    migrated, changed = migrate_resources(data)
    assert changed and data == original
    assert migrated["ai"]["provider"]["provider"] == OPENAI_COMPATIBLE_PROVIDER
    (tmp_path / "resources.json").write_bytes(orjson.dumps(data))
    reopened = ResourceStore(store.location)
    assert reopened.get("ai", "provider").provider == OPENAI_COMPATIBLE_PROVIDER
    saved = orjson.loads((tmp_path / "resources.json").read_bytes())
    assert saved["ai"]["provider"]["provider"] == OPENAI_COMPATIBLE_PROVIDER
    assert migrate_resources(saved)[1] is False


def test_saved_run_alias_is_normalized_before_snapshot_validation():
    data = snapshot().model_dump(mode="json")
    data["ai"]["ai"]["provider"] = "http"
    original = deepcopy(data)
    restored = WorkflowSnapshot.model_validate(migrate_legacy_snapshot(data))
    assert restored.ai["ai"].provider == OPENAI_COMPATIBLE_PROVIDER
    assert data == original
    assert restored.workflow.model_dump(mode="json") == data["workflow"]


def test_new_provider_input_uses_only_the_registered_identifier(tmp_path):
    factory = OpenAIChannelFactory()
    providers = {OPENAI_COMPATIBLE_PROVIDER: factory}
    store = ResourceStore(tmp_path / "resources.json", validators={
        "ai": lambda config: validate_config(config, providers),
    })
    config = AIConfig(id="provider", provider="http", base_url="http://provider.test/v1")
    with pytest.raises(WorkFLowWeaveError) as caught:
        store.save("ai", config)
    assert caught.value.code == "provider_missing"
    assert store.list("ai") == []
    config.provider = OPENAI_COMPATIBLE_PROVIDER
    assert store.save("ai", config).provider == OPENAI_COMPATIBLE_PROVIDER
