"""Compatibility imports for callers of the original Agent command API."""

from logagent.agent.commands import AgentChannel, AgentCommand, parse_command

__all__ = ["AgentChannel", "AgentCommand", "parse_command"]
