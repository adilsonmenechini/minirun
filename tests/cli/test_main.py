from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minirun.cli.main import (
    _activate_profile,
    _list_commands,
    _list_skills,
    _parse_profile_reference,
    build_parser,
    dispatch_listing,
    run,
)
from minirun.ports.provider import Message
from minirun.workspace.models import MCPServerConfig, WorkspaceProfile


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
            patch("minirun.cli.main.finalize_session"),
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
            patch("minirun.cli.main.finalize_session"),
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
            patch("minirun.cli.main.finalize_session"),
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

    async def test_run_with_profile_name(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run() with @profile_name activates profile, injects system prompt."""
        mock_response = MagicMock()
        mock_response.content = "Profile response!"
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(return_value=mock_response)

        mock_profile = WorkspaceProfile(
            name="sre",
            description="SRE specialist",
            system_prompt="You are an SRE specialist.",
            allowed_tools=["datadog-mcp.query_logs"],
            mcp_servers=[
                MCPServerConfig(
                    name="dd",
                    transport="stdio",
                    command="datadog-mcp",
                )
            ],
        )

        with (
            patch("minirun.cli.main.boot_init"),
            patch("minirun.cli.main.get_provider", return_value=mock_provider),
            patch("minirun.cli.main.finalize_session"),
            patch("minirun.cli.main.bootstrap_workspace_async"),
            patch("minirun.cli.main.WorkspaceDiscovery") as mock_discovery_cls,
        ):
            mock_discovery = MagicMock()
            mock_discovery.get_profile.return_value = mock_profile
            mock_discovery_cls.return_value = mock_discovery

            await run(
                provider_name="openai",
                model=None,
                temperature=None,
                max_tokens=None,
                message="@sre pesquisa sobre datadog",
            )

        captured = capsys.readouterr()
        assert "Profile response!" in captured.out
        mock_provider.complete.assert_awaited_once()

        # Verify the system prompt was injected (clean message without @sre)
        call_args = mock_provider.complete.await_args
        assert call_args is not None
        sent_messages = call_args[0][0]
        assert any(
            msg.role == "system" and "SRE specialist" in msg.content
            for msg in sent_messages
        )
        assert any(
            msg.role == "user" and "pesquisa sobre datadog" in msg.content
            for msg in sent_messages
        )


class TestParseProfileReference:
    """Tests for _parse_profile_reference(): the @profile_name parser."""

    def test_parses_basic_profile(self) -> None:
        profile, message = _parse_profile_reference("@sre hi")
        assert profile == "sre"
        assert message == "hi"

    def test_parses_dotted_profile_name(self) -> None:
        profile, message = _parse_profile_reference("@datadog-mcp query logs")
        assert profile == "datadog-mcp"
        assert message == "query logs"

    def test_parses_dotted_with_dots(self) -> None:
        profile, message = _parse_profile_reference("@my.profile run")
        assert profile == "my.profile"
        assert message == "run"

    def test_profile_only_no_message(self) -> None:
        profile, message = _parse_profile_reference("@sre")
        assert profile == "sre"
        assert message == ""

    def test_profile_with_trailing_spaces(self) -> None:
        profile, message = _parse_profile_reference("@sre   ")
        assert profile == "sre"
        assert message == ""

    def test_no_profile(self) -> None:
        profile, message = _parse_profile_reference("hello world")
        assert profile is None
        assert message == "hello world"

    def test_not_at_start_returns_none(self) -> None:
        """@profile must be at the start of the message."""
        profile, message = _parse_profile_reference("hi @sre")
        assert profile is None
        assert message == "hi @sre"

    def test_at_symbol_alone(self) -> None:
        profile, message = _parse_profile_reference("@")
        assert profile is None
        assert message == "@"

    def test_empty_string(self) -> None:
        profile, message = _parse_profile_reference("")
        assert profile is None
        assert message == ""

    def test_multiline_message(self) -> None:
        profile, message = _parse_profile_reference("@sre help\nshow logs")
        assert profile == "sre"
        assert "help" in message
        assert "show logs" in message


class TestActivateProfile:
    """Tests for _activate_profile(): injecting profile system_prompt into messages."""

    def test_injects_system_prompt_at_start(self) -> None:
        profile = WorkspaceProfile(
            name="sre",
            system_prompt="You are an SRE specialist.",
        )
        messages: list[Message] = [
            Message(role="user", content="hi"),
        ]
        _activate_profile(profile, messages)

        assert len(messages) == 2
        assert messages[0].role == "system"
        assert "SRE specialist" in messages[0].content
        assert messages[1].role == "user"

    def test_prepends_to_existing_system_message(self) -> None:
        profile = WorkspaceProfile(
            name="sre",
            system_prompt="You are an SRE specialist.",
        )
        messages: list[Message] = [
            Message(role="system", content="Memory context"),
            Message(role="user", content="hi"),
        ]
        _activate_profile(profile, messages)

        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[0].content.startswith("You are an SRE specialist.")
        assert "Memory context" in messages[0].content

    def test_noop_when_no_system_prompt(self) -> None:
        profile = WorkspaceProfile(
            name="sre",
            system_prompt="",
        )
        messages: list[Message] = [
            Message(role="user", content="hi"),
        ]
        _activate_profile(profile, messages)

        assert len(messages) == 1  # unchanged

    def test_does_not_duplicate_on_multiple_calls(self) -> None:
        profile = WorkspaceProfile(
            name="sre",
            system_prompt="You are an SRE specialist.",
        )
        messages: list[Message] = []

        _activate_profile(profile, messages)
        _activate_profile(profile, messages)

        # Second call prepends to existing system message
        assert len(messages) == 1
        assert messages[0].role == "system"
        assert "You are an SRE specialist." in messages[0].content


class TestCliSkillAndCommandListing:
    """Tests for _list_skills() and _list_commands().

    Used in chat via /skills and /commands.
    """

    def test_list_skills_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When no skills, prints 'No skills found'."""
        with patch("minirun.cli.main.Workspace") as mock_ws_cls:
            mock_ws = MagicMock()
            mock_ws.discover_skills.return_value = []
            mock_ws_cls.return_value = mock_ws
            _list_skills()
        captured = capsys.readouterr()
        assert "No skills found" in captured.out

    def test_list_skills_with_items(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When skills exist, prints their names, descriptions, and formats."""
        with patch("minirun.cli.main.Workspace") as mock_ws_cls:
            mock_ws = MagicMock()
            mock_ws.discover_skills.return_value = [
                {
                    "name": "deploy",
                    "description": "Deploy skill",
                    "format": "yaml",
                    "path": "/workspace/skills/deploy.yaml",
                },
                {
                    "name": "k8s-debug",
                    "description": "Debug K8s workloads",
                    "format": "md",
                    "path": "/workspace/skills/k8s-debug.md",
                },
            ]
            mock_ws_cls.return_value = mock_ws
            _list_skills()
        captured = capsys.readouterr()
        assert "deploy" in captured.out
        assert "k8s-debug" in captured.out
        assert "Deploy skill" in captured.out
        assert "Debug K8s" in captured.out

    def test_list_commands_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When no commands, prints 'No commands found'."""
        with patch("minirun.cli.main.Workspace") as mock_ws_cls:
            mock_ws = MagicMock()
            mock_ws.discover_commands.return_value = []
            mock_ws_cls.return_value = mock_ws
            _list_commands()
        captured = capsys.readouterr()
        assert "No commands found" in captured.out

    def test_list_commands_with_items(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When commands exist, prints their names, descriptions, and formats."""
        with patch("minirun.cli.main.Workspace") as mock_ws_cls:
            mock_ws = MagicMock()
            mock_ws.discover_commands.return_value = [
                {
                    "name": "deploy",
                    "description": "Deploy to prod",
                    "format": "sh",
                    "path": "/workspace/commands/deploy.sh",
                },
                {
                    "name": "backup",
                    "description": "Backup database",
                    "format": "md",
                    "path": "/workspace/commands/backup.md",
                },
            ]
            mock_ws_cls.return_value = mock_ws
            _list_commands()
        captured = capsys.readouterr()
        assert "deploy" in captured.out
        assert "backup" in captured.out
        assert "Deploy to prod" in captured.out
        assert "Backup database" in captured.out
        assert "sh" in captured.out
        assert "md" in captured.out
