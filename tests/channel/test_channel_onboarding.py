"""Documented channel onboarding examples use actual storage paths."""

from workflowweave.config.normalize import normalize_options
from workflowweave.models import ChannelConfig, Notification
from workflowweave.plugins.channel.file.channel import FileChannel, FileChannelType


async def test_documented_file_path_resolves_and_writes_under_data_dir(tmp_path):
    options = normalize_options(
        {"path": "logs/notifications.log"}, FileChannelType.options_schema,
        data_dir=tmp_path, apply_defaults=True,
    )
    channel = FileChannel(ChannelConfig(id="file", channel="file", options=options))
    await channel.start()
    try:
        await channel.send(Notification(
            session_id="example", output_id="test", title="Path example", text="written",
        ), options={})
    finally:
        await channel.stop()
    assert "written" in (tmp_path / "logs/notifications.log").read_text(encoding="utf-8")
