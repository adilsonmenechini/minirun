import pytest

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
    call_with_retry,
)


class TestProviderInterface:
    def test_message_dataclass(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.name is None
        assert msg.tool_call_id is None

    def test_message_with_optional_fields(self):
        msg = Message(
            role="tool",
            content='{"result": "ok"}',
            name="get_weather",
            tool_call_id="call_123",
        )
        assert msg.name == "get_weather"
        assert msg.tool_call_id == "call_123"

    def test_tool_dataclass(self):
        tool = Tool(
            name="read_file",
            description="Read a file",
            parameters={"type": "object"},
        )
        assert tool.name == "read_file"
        assert tool.description == "Read a file"

    def test_tool_call_dataclass(self):
        tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "NYC"})
        assert tc.id == "call_1"
        assert tc.name == "get_weather"
        assert tc.arguments == {"city": "NYC"}

    def test_tool_result_dataclass(self):
        tr = ToolResult(output="sunny", success=True)
        assert tr.output == "sunny"
        assert tr.success is True
        assert tr.error is None

    def test_response_dataclass(self):
        usage = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        resp = Response(content="Hello!", usage=usage)
        assert resp.content == "Hello!"
        assert resp.usage is not None
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.total_tokens == 15

    def test_response_with_tool_calls(self):
        tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "NYC"})
        resp = Response(content="", tool_calls=[tc])
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1

    def test_base_provider_abstract(self):
        with pytest.raises(TypeError):
            BaseProvider()  # type: ignore[abstract]


class TestProviderErrors:
    def test_authentication_error(self):
        err = AuthenticationError("Invalid API key")
        assert str(err) == "Invalid API key"
        assert isinstance(err, Exception)

    def test_rate_limit_error(self):
        err = RateLimitError("Too many requests")
        assert str(err) == "Too many requests"

    def test_connection_error(self):
        err = ConnectionError("Connection refused")
        assert str(err) == "Connection refused"

    def test_model_not_found_error(self):
        err = ModelNotFoundError("Model not available")
        assert str(err) == "Model not available"

    def test_provider_error(self):
        err = ProviderError("Unexpected response")
        assert str(err) == "Unexpected response"

    def test_all_errors_importable(self):
        from minirun.providers import (  # noqa: F811
            AuthenticationError,
            ConnectionError,
            ModelNotFoundError,
            ProviderError,
            RateLimitError,
        )

        assert AuthenticationError is not None
        assert RateLimitError is not None
        assert ConnectionError is not None
        assert ModelNotFoundError is not None
        assert ProviderError is not None


class TestRetry:
    async def test_retry_success_after_failures(self):
        call_count = 0

        async def flaky_op():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError("too fast")
            return "ok"

        result = await call_with_retry(flaky_op, max_retries=3)
        assert result == "ok"
        assert call_count == 3

    async def test_retry_exhausted(self):
        async def always_fails():
            raise RateLimitError("always rate limited")

        with pytest.raises(RateLimitError, match="always rate limited"):
            await call_with_retry(always_fails, max_retries=2)

    async def test_retry_does_not_retry_auth_error(self):
        call_count = 0

        async def auth_op():
            nonlocal call_count
            call_count += 1
            raise AuthenticationError("bad key")

        with pytest.raises(AuthenticationError, match="bad key"):
            await call_with_retry(auth_op, max_retries=3)

        assert call_count == 1, "Should not retry auth errors"

    async def test_retry_does_not_retry_model_not_found(self):
        call_count = 0

        async def model_op():
            nonlocal call_count
            call_count += 1
            raise ModelNotFoundError("unknown model")

        with pytest.raises(ModelNotFoundError, match="unknown model"):
            await call_with_retry(model_op, max_retries=3)

        assert call_count == 1, "Should not retry model-not-found errors"
