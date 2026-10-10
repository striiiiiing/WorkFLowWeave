"""Collection prerequisites owned by the configuration module."""

from workflowweave.config.credentials import CredentialManager
from workflowweave.config.reader import ConfigurationReader
from workflowweave.config.registry import ChannelPluginApi, PluginRegistry
from workflowweave.config.store import ResourceStore
from workflowweave.config.views import ChannelRegister

__all__ = [
    "ChannelPluginApi",
    "ChannelRegister",
    "ConfigurationReader",
    "CredentialManager",
    "PluginRegistry",
    "ResourceStore",
]
