"""六渠道分组注册、能力矩阵、跨层冲突和缺失可选 SDK 的诊断隔离。"""

from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path

import pytest

from tests.fixtures.plugin_helpers import install_plugin
from workflowweave.config.registry import PluginRegistry
from workflowweave.models import SystemConfig


def test_channel_group_is_discovered(tmp_path):
    async def discover():
        registry = PluginRegistry()
        return await registry.reload_plugins(
            SystemConfig(
                plugin_dir=str(tmp_path / "user-plugins"),
                data_dir=str(tmp_path / "data"),
            )
        )

    report = asyncio.run(discover())
    channels = {item.name: tuple(item.capabilities) for item in report.registered if item.kind == "channel"}
    assert channels == {
        "email": ("notification",),
        "file": ("notification",),
        "qq": ("notification", "conversation"),
        "wechat_openclaw": ("notification", "conversation"),
        "feishu": ("notification", "conversation"),
        "telegram": ("notification", "conversation"),
    }
    assert not report.errors


async def test_root_and_grouped_plugins_share_one_identity_namespace(tmp_path):
    source = Path(__file__).parents[2] / "src/workflowweave/plugins/channel/file"
    install_plugin(source, tmp_path / "file")
    install_plugin(source, tmp_path / "channel/file")
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(
        plugin_dir=str(tmp_path),
        builtin_plugin_dir=str(tmp_path.parent / f"{tmp_path.name}-builtins"),
    ))
    assert [item.name for item in report.registered if item.kind == "channel"] == ["file"]
    assert len(report.errors) == 1
    assert report.errors[0].details["reason"] == "plugin_id_conflict"


@pytest.mark.parametrize("group", ["tool"])
async def test_manifest_kind_must_match_group_before_import(tmp_path, group):
    location = install_plugin(
        Path(__file__).parents[2] / "src/workflowweave/plugins/channel/file",
        tmp_path / group / "file",
    )
    (location / "main.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")
    report = await PluginRegistry().discover_plugins(SystemConfig(
        plugin_dir=str(tmp_path),
        builtin_plugin_dir=str(tmp_path.parent / f"{tmp_path.name}-builtins"),
    ))
    assert not [item for item in report.registered if item.kind == "channel"]
    assert len(report.errors) == 1
    assert report.errors[0].details["stage"] == "manifest"
    assert report.errors[0].details["reason"] == "invalid_declaration"


async def test_missing_optional_sdk_only_disables_its_plugin(tmp_path, monkeypatch):
    source = Path(__file__).parents[2] / "src/workflowweave/plugins/channel"
    for name in ("email", "file"):
        install_plugin(source / name, tmp_path / "channel" / name)
    original_import = builtins.__import__

    def without_smtp(name, *args, **kwargs):
        if name == "aiosmtplib":
            raise ModuleNotFoundError("private dependency diagnostic")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_smtp)
    report = await PluginRegistry().discover_plugins(SystemConfig(
        plugin_dir=str(tmp_path),
        builtin_plugin_dir=str(tmp_path.parent / f"{tmp_path.name}-builtins"),
    ))
    assert [item.name for item in report.registered if item.kind == "channel"] == ["file"]
    assert len(report.errors) == 1
    assert report.errors[0].details["plugin"] == "email"
    assert "private" not in json.dumps(report.model_dump())
