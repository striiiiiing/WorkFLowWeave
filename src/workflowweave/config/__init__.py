"""Collection prerequisites owned by the configuration module."""

from workflowweave.config.credentials import CredentialManager
from workflowweave.config.normalize import expand_source
from workflowweave.config.reader import ConfigurationReader
from workflowweave.config.registry import ChannelPluginApi, CollectorPluginApi, PluginRegistry
from workflowweave.config.store import ResourceStore
from workflowweave.config.views import ChannelRegister, CollectorRegister

__all__ = [
    "ChannelPluginApi",
    "ChannelRegister",
    "CollectorPluginApi",
    "CollectorRegister",
    "ConfigurationReader",
    "CredentialManager",
    "PluginRegistry",
    "expand_source",
    "ResourceStore",
]
