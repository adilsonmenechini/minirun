from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minirun.adapters.openai import OpenAIProvider
from minirun.ports.provider import AuthenticationError, Message, Response


class TestOpenAIProvider:
    async def test_complete_returns_response(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content="Hello from OpenAI!",
                            tool_calls=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)

        messages = [Message(role="user", content="Say hello")]
        response = await provider.complete(messages)

        assert isinstance(response, Response)
        assert response.content == "Hello from OpenAI!"
        assert response.usage is not None
        assert response.usage.prompt_tokens == 10
        assert response.usage.total_tokens == 15

    async def test_complete_with_empty_content(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content=None, tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)

        messages = [Message(role="user", content="Say hello")]
        response = await provider.complete(messages)

        assert response.content == ""
        assert response.usage is None

    async def test_invalid_key_raises_authentication_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Incorrect API key provided")
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)

        messages = [Message(role="user", content="Say hello")]
        with pytest.raises(AuthenticationError):
            await provider.complete(messages)

    async def test_tool_calls_parsed_correctly(self):
        mock_client = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_1"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"city": "NYC"}'
        mock_tool_call.type = "function"

        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content=None,
                            tool_calls=[mock_tool_call],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)

        messages = [Message(role="user", content="What's the weather?")]
        response = await provider.complete(
            messages,
            tools=[],
        )

        assert response.content == ""
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "NYC"}

    async def test_custom_base_url_from_env(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="Hello!", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(
            api_key="sk-test-123",
            base_url="https://custom-proxy.example.com/v1",
            client=mock_client,
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "Hello!"

    async def test_default_url_when_no_base_url(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="OK", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "OK"

    async def test_model_override_via_constructor(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o-mini",
            )
        )
        provider = OpenAIProvider(
            api_key="sk-test-123", client=mock_client, model="gpt-4o-mini"
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        mock_client.chat.completions.create.assert_called_once()
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["model"] == "gpt-4o-mini"

    async def test_model_override_via_complete(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o-turbo",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages, model="gpt-4o-turbo")
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["model"] == "gpt-4o-turbo"

    async def test_temperature_via_constructor(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(
            api_key="sk-test-123", client=mock_client, temperature=0.5
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["temperature"] == 0.5

    async def test_temperature_via_complete(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages, temperature=0.2)
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["temperature"] == 0.2

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
                choices=[
                    MagicMock(
                        message=MagicMock(content="recovered", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )

        mock_client.chat.completions.create = _flaky
        provider = OpenAIProvider(
            api_key="sk-test-123", client=mock_client, max_retries=3
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
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )

        mock_client.chat.completions.create = _flaky
        provider = OpenAIProvider(
            api_key="sk-test-123", client=mock_client, max_retries=3
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        assert call_count == 3

    async def test_no_retry_on_auth_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Incorrect API key provided")
        )
        provider = OpenAIProvider(
            api_key="sk-test-123", client=mock_client, max_retries=3
        )
        messages = [Message(role="user", content="Hi")]
        with pytest.raises(AuthenticationError):
            await provider.complete(messages)
        assert mock_client.chat.completions.create.call_count == 1

    async def test_model_from_env_var(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o-turbo",
            )
        )
        with patch.dict("os.environ", {"LLM_MODEL": "gpt-4o-turbo"}):
            provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["model"] == "gpt-4o-turbo"

    async def test_max_tokens_via_constructor(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(
            api_key="sk-test-123", client=mock_client, max_tokens=2048
        )
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["max_tokens"] == 2048

    async def test_max_tokens_via_complete(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages, max_tokens=1024)
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["max_tokens"] == 1024

    async def test_max_tokens_from_env_var(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        with patch.dict("os.environ", {"LLM_MAX_TOKENS": "512"}):
            provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        _kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert _kwargs["max_tokens"] == 512

    async def test_max_tokens_not_passed_when_not_set(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="gpt-4o",
            )
        )
        provider = OpenAIProvider(api_key="sk-test-123", client=mock_client)
        messages = [Message(role="user", content="Hi")]
        response = await provider.complete(messages)
        assert response.content == "ok"
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "max_tokens" not in kwargs
