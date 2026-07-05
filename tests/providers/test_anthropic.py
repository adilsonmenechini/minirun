from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minirun.ports.provider import AuthenticationError, Message, Response
from minirun.providers.anthropic import AnthropicProvider


class TestAnthropicProvider:
    async def test_complete_returns_response(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="Hello from Anthropic!", type="text")],
                usage=MagicMock(
                    input_tokens=10,
                    output_tokens=5,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)

        messages = [Message(role="user", content="Say hello")]
        response = await provider.complete(messages)

        assert isinstance(response, Response)
        assert response.content == "Hello from Anthropic!"
        assert response.usage is not None
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5

    async def test_complete_with_empty_content(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="", type="text")],
                usage=MagicMock(
                    input_tokens=0,
                    output_tokens=0,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)

        messages = [Message(role="user", content="")]
        response = await provider.complete(messages)

        assert response.content == ""

    async def test_invalid_key_raises_authentication_error(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("Invalid API key")
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)

        messages = [Message(role="user", content="Say hello")]
        with pytest.raises(AuthenticationError):
            await provider.complete(messages)

    async def test_tool_calls_parsed_correctly(self):
        mock_client = MagicMock()

        mock_tool_use = MagicMock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.name = "get_weather"
        mock_tool_use.input = {"city": "NYC"}
        mock_tool_use.id = "toolu_1"

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Let me check the weather"

        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[mock_text_block, mock_tool_use],
                usage=MagicMock(
                    input_tokens=15,
                    output_tokens=12,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="tool_use",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)

        messages = [Message(role="user", content="What's the weather in NYC?")]
        response = await provider.complete(messages, tools=[])

        assert response.content == "Let me check the weather"
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "NYC"}

    async def test_custom_base_url_from_env(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="Hello!", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(
            api_key="sk-ant-test-123",
            base_url="https://custom-anthropic.example.com",
            client=mock_client,
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "Hello!"

    async def test_default_url_when_no_base_url(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="OK", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "OK"

    async def test_model_override_via_constructor(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-3-haiku-20240307",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(
            api_key="sk-ant-test-123",
            client=mock_client,
            model="claude-3-haiku-20240307",
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["model"] == "claude-3-haiku-20240307"

    async def test_model_override_via_complete(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-opus-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages, model="claude-opus-4-20250514")
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["model"] == "claude-opus-4-20250514"

    async def test_temperature_via_constructor(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(
            api_key="sk-ant-test-123", client=mock_client, temperature=0.8
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["temperature"] == 0.8

    async def test_temperature_via_complete(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages, temperature=0.1)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["temperature"] == 0.1

    async def test_retry_on_rate_limit_succeeds(self):
        mock_client = MagicMock()
        call_count = 0

        async def _flaky(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                msg = "rate limit exceeded"
                raise Exception(msg)
            return MagicMock(
                content=[MagicMock(text="recovered", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )

        mock_client.messages.create = _flaky
        provider = AnthropicProvider(
            api_key="sk-ant-test-123", client=mock_client, max_retries=3
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "recovered"
        assert call_count == 3

    async def test_retry_on_connection_error_succeeds(self):
        mock_client = MagicMock()
        call_count = 0

        async def _flaky(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                msg = "connection refused"
                raise Exception(msg)
            return MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )

        mock_client.messages.create = _flaky
        provider = AnthropicProvider(
            api_key="sk-ant-test-123", client=mock_client, max_retries=3
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        assert call_count == 3

    async def test_no_retry_on_auth_error(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("Invalid API key")
        )
        provider = AnthropicProvider(
            api_key="sk-ant-test-123", client=mock_client, max_retries=3
        )
        messages = [Message(role="user", content="Hi")]
        with pytest.raises(AuthenticationError):
            await provider.complete(messages)
        assert mock_client.messages.create.call_count == 1

    async def test_model_from_env_var(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-opus-4-20250514",
                stop_reason="end_turn",
            )
        )
        with patch.dict("os.environ", {"LLM_MODEL": "claude-opus-4-20250514"}):
            provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["model"] == "claude-opus-4-20250514"

    async def test_max_tokens_via_constructor(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(
            api_key="sk-ant-test-123", client=mock_client, max_tokens=8192
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["max_tokens"] == 8192

    async def test_max_tokens_via_complete(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages, max_tokens=2048)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["max_tokens"] == 2048

    async def test_max_tokens_from_env_var(self):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[MagicMock(text="ok", type="text")],
                usage=MagicMock(
                    input_tokens=5,
                    output_tokens=3,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                model="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
        )
        with patch.dict("os.environ", {"LLM_MAX_TOKENS": "2048"}):
            provider = AnthropicProvider(api_key="sk-ant-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.messages.create.call_args.kwargs
        assert _kwargs["max_tokens"] == 2048
