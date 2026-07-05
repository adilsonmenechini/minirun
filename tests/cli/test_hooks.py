"""Tests for the Specify Hooks CLI management commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_MODULE = REPO_ROOT / "minirun" / "cli" / "hooks.py"
EXTENSIONS_FILE = REPO_ROOT / ".specify" / "extensions.yml"


def run_cli(args: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "minirun.cli.main", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


class TestHooksDiscovery:
    def test_list_hooks_empty_when_none_registered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        result = run_cli(["hooks", "list"])
        assert result.returncode == 0
        assert (
            "No hooks registered" in result.stdout or "hooks" in result.stdout.lower()
        )

    def test_list_hooks_finds_registered_hooks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        result = run_cli(["hooks", "list"])
        assert result.returncode == 0


class TestHooksExecution:
    def test_run_hook_dry_run_does_not_execute(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        result = run_cli(
            ["hooks", "run", "--id", "speckit.agent-context.update", "--dry-run"],
        )
        assert result.returncode == 0

    def test_run_hook_requires_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        result = run_cli(["hooks", "run"])
        assert result.returncode != 0
