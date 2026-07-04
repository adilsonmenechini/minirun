"""LLM provider adapters (facade).

This module re-exports the port interface and concrete adapters.
The actual implementation lives in:
  - minirun.ports.provider   → BaseProvider (port interface) + data classes + errors
  - minirun.adapters.openai  → OpenAIProvider
  - minirun.adapters.anthropic → AnthropicProvider
"""

from minirun.adapters.anthropic import AnthropicProvider
from minirun.adapters.openai import OpenAIProvider
from minirun.ports.provider import (
    AuthenticationError,
    BaseProvider,
    ConnectionError,
    Message,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    Response,
    Tool,
    ToolCall,
    ToolResult,
    Usage,
)

PROVIDERS: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}

__all__ = [
    "BaseProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "PROVIDERS",
    "Message",
    "Tool",
    "Response",
    "ToolCall",
    "ToolResult",
    "Usage",
    "AuthenticationError",
    "RateLimitError",
    "ConnectionError",
    "ModelNotFoundError",
    "ProviderError",
]
