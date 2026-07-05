from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minirun.cli.main import build_parser, dispatch_listing, run


class TestCliParser:
    def test_provider_default(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.provider is None

    def test_provider_choice(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--provider", "anthropic"])
        assert args.provider == "anthropic"

    def test_invalid_provider(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--provider", "invalid"])

    def test_model_arg(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--model", "gpt-4o-mini"])
        assert args.model == "gpt-4o-mini"

    def test_temperature_arg(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--temperature", "0.5"])
        assert args.temperature == 0.5

    def test_max_tokens_arg(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--max-tokens", "2048"])
        assert args.max_tokens == 2048

    def test_positional_message(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["hello world"])
        assert args.message == ["hello world"]

    def test_message_with_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--model", "gpt-4o", "summarise", "this"])
        assert args.model == "gpt-4o"
        assert args.message == ["summarise", "this"]


class TestCliListing:
    def test_tools_flag_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--tools"])
        assert args.tools is True

    def test_profiles_flag_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--profiles"])
        assert args.profiles is True

    def test_skills_flag_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--skills"])
        assert args.skills is True

    def test_commands_flag_parsed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--commands"])
        assert args.commands is True

    def test_listing_flags_default_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.tools is False
        assert args.profiles is False
        assert args.skills is False
        assert args.commands is False

    def test_dispatch_tools_returns_true(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--tools"])
        assert dispatch_listing(args) is True

    def test_dispatch_no_listing_returns_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["hello"])
        assert dispatch_listing(args) is False


class TestCliRun:
    async def test_run_calls_provider_and_prints(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_response = MagicMock()
        mock_response.content = "Hello from mock!"
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value=mock_response)

        with (
            patch("minirun.cli.main.boot_init"),
            patch("minirun.cli.main.get_provider", return_value=mock_provider),
        ):
            await run(
                provider_name="openai",
                model=None,
                temperature=None,
                max_tokens=None,
                message="Say hi",
            )

        captured = capsys.readouterr()
        assert "Hello from mock!" in captured.out
        mock_provider.complete.assert_awaited_once()

    async def test_run_empty_message_exits(self) -> None:
        with (
            patch("minirun.cli.main.boot_init"),
            patch("minirun.cli.main.get_provider"),
            pytest.raises(SystemExit),
        ):
            await run(
                provider_name="openai",
                model=None,
                temperature=None,
                max_tokens=None,
                message="",
            )

    async def test_run_passes_overrides(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "ok"
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value=mock_response)

        with (
            patch("minirun.cli.main.boot_init"),
            patch("minirun.cli.main.get_provider") as mock_get,
        ):
            mock_get.return_value = mock_provider
            await run(
                provider_name="anthropic",
                model="claude-3-haiku-20240307",
                temperature=0.8,
                max_tokens=1024,
                message="test",
            )

        mock_get.assert_called_once_with(
            name="anthropic",
            model="claude-3-haiku-20240307",
            temperature=0.8,
            max_tokens=1024,
        )

    async def test_run_adds_newline_if_missing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_response = MagicMock()
        mock_response.content = "no newline"
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value=mock_response)

        with (
            patch("minirun.cli.main.boot_init"),
            patch("minirun.cli.main.get_provider", return_value=mock_provider),
        ):
            await run(
                provider_name="openai",
                model=None,
                temperature=None,
                max_tokens=None,
                message="test",
            )

        captured = capsys.readouterr()
        assert captured.out == "no newline\n"
