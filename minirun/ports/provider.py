from __future__ import annotations

import abc
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from minirun.log import get_logger


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    output: str
    success: bool = True
    error: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Response:
    content: str
    tool_calls: list[ToolCall] | None = None
    usage: Usage | None = None


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


class ConnectionError(Exception):
    pass


class ModelNotFoundError(Exception):
    pass


class ProviderError(Exception):
    pass


class BaseProvider(abc.ABC):
    @abc.abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Response:
        ...


async def call_with_retry(
    operation: Callable[[], Awaitable[Any]],
    max_retries: int = 3,
) -> Any:
    """Retry an async operation with exponential backoff on transient errors.

    Transient (retryable): RateLimitError, ConnectionError, ProviderError.
    Non-retryable (re-raised immediately): AuthenticationError, ModelNotFoundError.
    """
    log = get_logger("provider")

    for attempt in range(1, max_retries + 1):
        try:
            return await operation()
        except AuthenticationError:
            raise
        except ModelNotFoundError:
            raise
        except (RateLimitError, ConnectionError, ProviderError) as exc:
            if attempt < max_retries:
                wait = 2.0**attempt
                log.warning(
                    "Retry attempt %d/%d after %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
            else:
                raise

    raise RuntimeError("Unreachable")  # pragma: no cover
