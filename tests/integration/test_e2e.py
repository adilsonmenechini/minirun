from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minirun.ports.provider import Message
from minirun.runtime.harness import bootstrap, get_provider


class TestIntegrationE2E:
    @pytest.mark.asyncio
    async def test_provider_complete_e2e(self) -> None:
        with (
            patch.dict("os.environ", {"LLM_PROVIDER": "openai"}, clear=False),
            patch("minirun.runtime.harness.boot_init"),
            patch("minirun.workspace.Workspace.init", return_value=False),
        ):
            bootstrap()
            provider = get_provider(name="openai")

            mock_create = AsyncMock(
                return_value=MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content="Hello from E2E!",
                                tool_calls=None,
                                role="assistant",
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=MagicMock(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
                    model="gpt-4o",
                    id="chatcmpl-e2e",
                    object="chat.completion",
                )
            )

            with patch.object(provider, "_get_client") as mock_get_client:
                mock_client = MagicMock()
                mock_client.chat.completions.create = mock_create
                mock_get_client.return_value = mock_client

                response = await provider.complete(
                    [Message(role="user", content="Say hello")]
                )

            assert response.content == "Hello from E2E!"
            assert response.usage is not None
            assert response.usage.total_tokens == 15
            mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_anthropic_provider_e2e(self) -> None:
        with (
            patch.dict("os.environ", {"LLM_PROVIDER": "anthropic"}, clear=False),
            patch("minirun.runtime.harness.boot_init"),
            patch("minirun.workspace.Workspace.init", return_value=False),
        ):
            provider = get_provider(name="anthropic")

            content_block = MagicMock()
            content_block.type = "text"
            content_block.text = "Hello from Anthropic E2E!"
            mock_create = AsyncMock(
                return_value=MagicMock(
                    content=[content_block],
                    usage=MagicMock(input_tokens=10, output_tokens=5),
                    model="claude-sonnet-4-20250514",
                    id="msg_e2e",
                    stop_reason="end_turn",
                )
            )

            with patch.object(provider, "_get_client") as mock_get_client:
                mock_client = MagicMock()
                mock_client.messages.create = mock_create
                mock_get_client.return_value = mock_client

                response = await provider.complete(
                    [Message(role="user", content="Say hello")]
                )

            assert response.content == "Hello from Anthropic E2E!"
            assert response.usage is not None
            mock_create.assert_awaited_once()
