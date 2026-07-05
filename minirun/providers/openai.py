from __future__ import annotations

import json
import os
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

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

log = get_logger("providers.openai")


def _translate_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.name is not None:
            entry["name"] = msg.name
        if msg.tool_call_id is not None:
            entry["tool_call_id"] = msg.tool_call_id
        result.append(entry)
    return result


def _translate_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class OpenAIProvider(BaseProvider):
    MODEL = "gpt-4o"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_retries: int = 3,
        max_tokens: int | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self._base_url = base_url or os.environ.get("LLM_BASE_URL")
        self._client = client
        self._model = model or os.environ.get("LLM_MODEL") or self.MODEL
        self._temperature = temperature
        self._max_retries = max_retries
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            env_val = os.environ.get("LLM_MAX_TOKENS")
            self._max_tokens = int(env_val) if env_val is not None else None
        log.info(
            "init provider model=%s base=%s temp=%s retries=%d tokens=%s",
            self._model,
            self._base_url or "default",
            self._temperature if self._temperature is not None else "default",
            self._max_retries,
            self._max_tokens if self._max_tokens is not None else "default",
        )

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
            log.debug("new client base=%s", self._base_url or "default")
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

        openai_messages = _translate_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": openai_messages,
        }
        if tools:
            kwargs["tools"] = _translate_tools(tools)
            log.debug("tools=%d", len(tools))
        if temp is not None:
            kwargs["temperature"] = temp
        if tokens is not None:
            kwargs["max_tokens"] = tokens

        async def _do_request() -> ChatCompletion:
            try:
                return cast(
                    ChatCompletion,
                    await client.chat.completions.create(**kwargs),
                )
            except Exception as exc:
                msg = str(exc)
                log.warning("OpenAI API error: %s", msg)
                if "Incorrect API key" in msg or "invalid" in msg.lower():
                    raise AuthenticationError(msg) from exc
                if "rate" in msg.lower():
                    raise RateLimitError(msg) from exc
                if "not found" in msg.lower() or "not available" in msg.lower():
                    raise ModelNotFoundError(msg) from exc
                if "connect" in msg.lower() or "refused" in msg.lower():
                    raise ConnectionError(msg) from exc
                raise ProviderError(msg) from exc

        log.info(
            "chat %s msgs=%d tools=%s",
            model_name,
            len(messages),
            bool(tools),
        )

        raw = await call_with_retry(_do_request, max_retries=self._max_retries)
        response = cast(ChatCompletion, raw)

        choice = response.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls: list[ToolCall] | None = None

        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=fn.name,
                        arguments=json.loads(fn.arguments),
                    )
                )
            log.debug("tcalls=%d", len(tool_calls))

        usage: Usage | None = None
        if response.usage is not None:
            usage = Usage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )
            log.info("done tokens=%d/%d", usage.prompt_tokens, usage.completion_tokens)

        return Response(content=content, tool_calls=tool_calls, usage=usage)

    async def stream_complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Response:
        """Stream a chat completion, yielding tokens as they arrive."""
        import sys

        client = self._get_client()
        model_name = model or self._model
        temp = temperature if temperature is not None else self._temperature
        tokens = max_tokens if max_tokens is not None else self._max_tokens

        openai_messages = _translate_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": openai_messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = _translate_tools(tools)
        if temp is not None:
            kwargs["temperature"] = temp
        if tokens is not None:
            kwargs["max_tokens"] = tokens

        log.info("stream %s msgs=%d tools=%s", model_name, len(messages), bool(tools))

        collected: list[str] = []
        usage: Usage | None = None
        tool_calls: list[ToolCall] | None = None

        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None

                if delta and delta.content:
                    sys.stdout.write(delta.content)
                    sys.stdout.flush()
                    collected.append(delta.content)

                if delta and delta.tool_calls:
                    if tool_calls is None:
                        tool_calls = []
                    for tc in delta.tool_calls:
                        if len(tool_calls) <= tc.index:
                            tool_calls.append(
                                ToolCall(id="", name="", arguments={})
                            )
                        if tc.id:
                            tool_calls[tc.index].id = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls[tc.index].name = tc.function.name
                            if tc.function.arguments:
                                tc_args = tool_calls[tc.index].arguments
                                if isinstance(tc_args, dict):
                                    tc_args.clear()
                                try:
                                    parsed = json.loads(tc.function.arguments)
                                    if isinstance(parsed, dict):
                                        tool_calls[tc.index].arguments = parsed
                                except json.JSONDecodeError:
                                    pass

                if hasattr(chunk, "usage") and chunk.usage:
                    usage = Usage(
                        prompt_tokens=chunk.usage.prompt_tokens or 0,
                        completion_tokens=chunk.usage.completion_tokens or 0,
                        total_tokens=chunk.usage.total_tokens or 0,
                    )

        except Exception as exc:
            msg = str(exc)
            log.warning("OpenAI stream error: %s", msg)
            if "Incorrect API key" in msg or "invalid" in msg.lower():
                raise AuthenticationError(msg) from exc
            if "rate" in msg.lower():
                raise RateLimitError(msg) from exc
            if "not found" in msg.lower() or "not available" in msg.lower():
                raise ModelNotFoundError(msg) from exc
            if "connect" in msg.lower() or "refused" in msg.lower():
                raise ConnectionError(msg) from exc
            raise ProviderError(msg) from exc

        if usage is not None:
            log.info(
                "done tokens=%d/%d", usage.prompt_tokens, usage.completion_tokens
            )

        return Response(
            content="".join(collected),
            tool_calls=tool_calls,
            usage=usage,
        )
