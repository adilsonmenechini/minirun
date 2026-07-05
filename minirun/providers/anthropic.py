from __future__ import annotations

from typing import Any

from minirun.log import get_logger
from minirun.ports.provider import BaseProvider, Message, Response

log = get_logger("providers.anthropic")


class AnthropicProvider(BaseProvider):
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "Anthropic provider requires the 'anthropic' package. "
            "Install it with: pip install anthropic"
        )

    async def complete(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Response:  # pragma: no cover
        raise RuntimeError("Anthropic provider not available")
