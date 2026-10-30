"""Explicit provider adapters and their shared fetch contract."""

from cli_usage_api.providers.base import Provider, build_providers
from cli_usage_api.providers.claude import ClaudeProvider
from cli_usage_api.providers.codex import CodexProvider
from cli_usage_api.providers.console import ConsoleProvider
from cli_usage_api.providers.grok import GrokProvider
from cli_usage_api.providers.openai_platform import OpenAIPlatformProvider

__all__ = [
    "ClaudeProvider",
    "CodexProvider",
    "ConsoleProvider",
    "GrokProvider",
    "OpenAIPlatformProvider",
    "Provider",
    "build_providers",
]
