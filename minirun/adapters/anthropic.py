from __future__ import annotations

import os
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import (
    Message as AnthropicMessage,
)

from minirun.log import get_logger
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
    Usage,
    call_with_retry,
)

log = get_logger("adapters.anthropic")


def _translate_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id is not None:
            entry["tool_call_id"] = msg.tool_call_id
        result.append(entry)
    return result


def _translate_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


class AnthropicProvider(BaseProvider):
    MODEL = "claude-sonnet-4-20250514"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client: AsyncAnthropic | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_retries: int = 3,
        max_tokens: int | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self._base_url = base_url or os.environ.get("LLM_BASE_URL")
        self._client = client
        self._model = (
            model
            or os.environ.get("LLM_MODEL")
            or self.MODEL
        )
        self._temperature = temperature
        self._max_retries = max_retries
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            env_val = os.environ.get("LLM_MAX_TOKENS")
            self._max_tokens = int(env_val) if env_val is not None else 4096
        log.info(
            "Initialised Anthropic provider "
            "(model=%s, base_url=%s, temperature=%s, max_retries=%d, max_tokens=%d)",
            self._model,
            self._base_url or "default",
            self._temperature if self._temperature is not None else "default",
            self._max_retries,
            self._max_tokens,
        )

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncAnthropic(**kwargs)
            log.debug(
                "Created Anthropic SDK client (base_url=%s)",
                self._base_url or "default",
            )
        return self._client

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Response:
        client = self._get_client()
        model_name = model or self._model
        temp = temperature if temperature is not None else self._temperature
        tokens = max_tokens if max_tokens is not None else self._max_tokens

        anthropic_messages = _translate_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": tokens,
            "messages": anthropic_messages,
        }
        if tools:
            kwargs["tools"] = _translate_tools(tools)
            log.debug("Request includes %d tool(s)", len(tools))
        if temp is not None:
            kwargs["temperature"] = temp

        async def _do_request() -> Any:
            try:
                return await client.messages.create(**kwargs)
            except Exception as exc:
                msg = str(exc)
                log.warning("Anthropic API error: %s", msg)
                if "Invalid API key" in msg or "invalid" in msg.lower():
                    raise AuthenticationError(msg) from exc
                if "rate" in msg.lower():
                    raise RateLimitError(msg) from exc
                if "not found" in msg.lower() or "not available" in msg.lower():
                    raise ModelNotFoundError(msg) from exc
                if "connect" in msg.lower() or "refused" in msg.lower():
                    raise ConnectionError(msg) from exc
                raise ProviderError(msg) from exc

        log.info(
            "Sending message "
            "(model=%s, messages=%d, tools=%s, temperature=%s, max_tokens=%d)",
            model_name,
            len(messages),
            "yes" if tools else "no",
            temp if temp is not None else "default",
            tokens,
        )

        raw = await call_with_retry(_do_request, max_retries=self._max_retries)
        response = cast(AnthropicMessage, raw)

        content_parts: list[str] = []
        tool_calls: list[ToolCall] | None = None

        for block in response.content:
            block_type = getattr(block, "type", "")
            if block_type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input),
                    )
                )
            elif block_type == "text":
                text = getattr(block, "text", "")
                if text:
                    content_parts.append(block.text)

        if tool_calls:
            log.debug("Parsed %d tool use(s) from response", len(tool_calls))

        usage: Usage | None = None
        if response.usage is not None:
            usage = Usage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            )
            log.info(
                "Message finished (tokens=%d/%d)",
                usage.prompt_tokens,
                usage.completion_tokens,
            )

        return Response(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
        )
