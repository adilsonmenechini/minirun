from __future__ import annotations

import pytest

from minirun.tools.shell import ShellTool


@pytest.fixture
def tool() -> ShellTool:
    return ShellTool()


class TestShellExec:
    def test_exec_runs_command_and_returns_stdout(self, tool: ShellTool) -> None:
        result = tool.execute({"command": "echo hello world"})
        assert result["success"] is True
        assert result["data"]["stdout"].strip() == "hello world"
        assert result["data"]["exit_code"] == 0

    def test_exec_returns_stderr_for_failing_command(self, tool: ShellTool) -> None:
        result = tool.execute({"command": "echo stderr_msg >&2 && exit 1"})
        assert result["success"] is False
        assert result["data"]["exit_code"] == 1
        assert "stderr_msg" in result["data"]["stderr"]

    def test_exec_missing_command(self, tool: ShellTool) -> None:
        result = tool.execute({})
        assert result["success"] is False
        assert "missing" in result["error"].lower()

    def test_exec_empty_command(self, tool: ShellTool) -> None:
        result = tool.execute({"command": ""})
        assert result["success"] is False
        assert "missing" in result["error"].lower()

    def test_exec_timeout_kills_long_process(self, tool: ShellTool) -> None:
        result = tool.execute({"command": "sleep 10", "timeout": 1})
        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert result["data"]["exit_code"] == -1
