"""Tests for workspace commands and skills: models, discovery, execution.

Covers:
- WorkspaceSkill / SkillTool model parsing and validation
- WorkspaceCommand model parsing (.sh, .md, .py)
- WorkspaceDiscovery: get_skill(), get_command(), discover_extensions()
- WorkspaceExecutor: execute_skill_tool with python/shell/mcp handlers
- Edge cases: non-executable commands, duplicate tools, empty directories
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from minirun.workspace.discovery import WorkspaceDiscovery
from minirun.workspace.executor import WorkspaceExecutor, _build_shell_args
from minirun.workspace.models import (
    SkillTool,
    WorkspaceCommand,
    WorkspaceProfile,
    WorkspaceSkill,
)

# ═══════════════════════════════════════════════════════════════════════
#  1. SkillTool model
# ═══════════════════════════════════════════════════════════════════════


class TestSkillTool:
    """Tests for the SkillTool dataclass."""

    def test_default_values(self) -> None:
        tool = SkillTool(name="deploy")
        assert tool.name == "deploy"
        assert tool.description == ""
        assert tool.input_schema is None
        assert tool.handler == ""

    def test_with_all_fields(self) -> None:
        tool = SkillTool(
            name="deploy",
            description="Deploy to production",
            input_schema={"type": "object", "properties": {}},
            handler="python:deploy_tools:run_deploy",
        )
        assert tool.name == "deploy"
        assert tool.description == "Deploy to production"
        assert tool.input_schema == {"type": "object", "properties": {}}
        assert tool.handler == "python:deploy_tools:run_deploy"


# ═══════════════════════════════════════════════════════════════════════
#  2. WorkspaceSkill model
# ═══════════════════════════════════════════════════════════════════════


class TestWorkspaceSkill:
    """Tests for WorkspaceSkill.from_file() — parsing YAML skill definitions."""

    def test_from_file_basic(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text(
            "name: deploy\nversion: 1.0.0\ndescription: Deploy skill\n"
            "tools:\n"
            "  - name: run\n"
            "    handler: shell:deploy.sh\n"
        )
        skill = WorkspaceSkill.from_file(s / "deploy.yaml")
        assert skill.name == "deploy"
        assert skill.version == "1.0.0"
        assert skill.description == "Deploy skill"
        assert len(skill.tools) == 1
        assert skill.tools[0].name == "run"
        assert skill.tools[0].handler == "shell:deploy.sh"

    def test_from_file_with_timeout(self, tmp_path: Path) -> None:
        """FR-011: configurable execution timeout."""
        s = tmp_path / "skills"
        s.mkdir()
        (s / "backup.yaml").write_text(
            "name: backup\nversion: 1\ntimeout: 60\n"
            "tools:\n"
            "  - name: run\n"
            "    handler: shell:backup.sh\n"
        )
        skill = WorkspaceSkill.from_file(s / "backup.yaml")
        assert skill.name == "backup"
        assert skill.timeout == 60

    def test_default_timeout_is_none(self, tmp_path: Path) -> None:
        """When timeout is not specified, it defaults to None (runtime uses 30s)."""
        s = tmp_path / "skills"
        s.mkdir()
        (s / "quick.yaml").write_text("name: quick\nversion: 1\n")
        skill = WorkspaceSkill.from_file(s / "quick.yaml")
        assert skill.timeout is None

    def test_from_file_with_input_schema(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "db.yaml").write_text(
            "name: db\nversion: 1\n"
            "tools:\n"
            "  - name: query\n"
            "    description: Run SQL query\n"
            "    input_schema:\n"
            "      type: object\n"
            "      properties:\n"
            "        sql:\n"
            "          type: string\n"
            "    handler: python:db:run_query\n"
        )
        skill = WorkspaceSkill.from_file(s / "db.yaml")
        assert len(skill.tools) == 1
        tool = skill.tools[0]
        assert tool.name == "query"
        assert tool.input_schema is not None
        assert tool.input_schema["type"] == "object"

    def test_from_file_unknown_extras_ignored(self, tmp_path: Path) -> None:
        """Extra fields in YAML are silently ignored."""
        s = tmp_path / "skills"
        s.mkdir()
        (s / "x.yaml").write_text(
            "name: x\nversion: 1\nextra_field: should_be_ignored\n"
        )
        skill = WorkspaceSkill.from_file(s / "x.yaml")
        assert skill.name == "x"

    def test_from_file_missing_tools_defaults_empty(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "simple.yaml").write_text("name: simple\nversion: 1\n")
        skill = WorkspaceSkill.from_file(s / "simple.yaml")
        assert skill.tools == []


# ═══════════════════════════════════════════════════════════════════════
#  3. WorkspaceCommand model
# ═══════════════════════════════════════════════════════════════════════


class TestWorkspaceCommand:
    """Tests for WorkspaceCommand.from_file() — .sh, .md, .py files."""

    def test_from_file_sh(self, tmp_path: Path) -> None:
        f = tmp_path / "deploy.sh"
        f.write_text("#!/bin/bash\necho deploy")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "deploy"
        assert cmd.type == "shell"
        assert cmd.path == str(f)
        assert cmd.description == ""

    def test_from_file_py(self, tmp_path: Path) -> None:
        f = tmp_path / "build.py"
        f.write_text("print('build')")
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "build"
        assert cmd.type == "python"
        assert cmd.path == str(f)

    def test_from_file_md_with_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "sync.md"
        f.write_text(
            "---\nname: sync-data\ndescription: Sync data\ntype: python\n---\n"
        )
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "sync-data"
        assert cmd.description == "Sync data"
        assert cmd.type == "python"

    def test_from_file_md_without_frontmatter(self, tmp_path: Path) -> None:
        """Fallback to filename stem and shell type when .md has no frontmatter."""
        f = tmp_path / "script.md"
        f.write_text("# Just a script description\n")
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "script"
        assert cmd.type == "shell"

    def test_from_file_unknown_extension_is_shell(self, tmp_path: Path) -> None:
        f = tmp_path / "custom.xyz"
        f.write_text("echo custom")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "custom"
        assert cmd.type == "shell"


# ═══════════════════════════════════════════════════════════════════════
#  4. WorkspaceDiscovery — skills, commands, extensions, overrides
# ═══════════════════════════════════════════════════════════════════════


class TestDiscoverySkills:
    """Tests for WorkspaceDiscovery discover_skills() and get_skill()."""

    def test_discover_skills_empty(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.discover_skills() == []

    def test_discover_skills_multiple(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text("name: deploy\nversion: 1\n")
        (s / "backup.yaml").write_text("name: backup\nversion: 1\n")
        d = WorkspaceDiscovery(tmp_path)
        skills = d.discover_skills()
        assert len(skills) == 2
        names = {sk.name for sk in skills}
        assert names == {"deploy", "backup"}

    def test_discover_skills_skips_invalid_yaml(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "good.yaml").write_text("name: good\nversion: 1\n")
        (s / "bad.yaml").write_text("name: bad\nversion: [invalid")
        d = WorkspaceDiscovery(tmp_path)
        skills = d.discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "good"

    def test_get_skill_by_name(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text("name: deploy\nversion: 1\n")
        d = WorkspaceDiscovery(tmp_path)
        skill = d.get_skill("deploy")
        assert skill is not None
        assert skill.name == "deploy"

    def test_get_skill_nonexistent(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.get_skill("nonexistent") is None


class TestDiscoveryCommands:
    """Tests for WorkspaceDiscovery discover_commands() and get_command()."""

    def test_discover_commands_empty(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.discover_commands() == []

    def test_discover_commands_executable(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "hello.sh"
        f.write_text("#!/bin/bash\necho hello")
        f.chmod(0o755)
        d = WorkspaceDiscovery(tmp_path)
        cmds = d.discover_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "hello"

    def test_discover_commands_skips_non_executable(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-executable .sh files are skipped with warning."""
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "skip.sh"
        f.write_text("#!/bin/bash\necho skip")
        # Don't set +x — file remains non-executable
        d = WorkspaceDiscovery(tmp_path)
        cmds = d.discover_commands()
        assert cmds == []

    def test_get_command_by_name(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "hello.sh"
        f.write_text("#!/bin/bash\necho hello")
        f.chmod(0o755)
        d = WorkspaceDiscovery(tmp_path)
        cmd = d.get_command("hello")
        assert cmd is not None
        assert cmd.name == "hello"

    def test_get_command_nonexistent(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.get_command("nonexistent") is None


class TestDiscoveryExtensions:
    """Tests for WorkspaceDiscovery discover_extensions() and get_extension()."""

    def test_discover_extensions_empty(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.discover_extensions() == []

    def test_discover_extensions_finds_yaml(self, tmp_path: Path) -> None:
        ext_dir = tmp_path / "profiles" / "extensions"
        ext_dir.mkdir(parents=True)
        (ext_dir / "oncall.yaml").write_text(
            "name: oncall\ndescription: On-call extension\n"
            "profile: sre\ninstructions: Follow on-call procedures\n"
            "allowed_tools:\n  - pagerduty-mcp.acknowledge\n"
        )
        d = WorkspaceDiscovery(tmp_path)
        exts = d.discover_extensions()
        assert len(exts) == 1
        assert exts[0].name == "oncall"
        assert exts[0].profile == "sre"
        assert "pagerduty-mcp.acknowledge" in exts[0].allowed_tools

    def test_get_extension_by_name(self, tmp_path: Path) -> None:
        ext_dir = tmp_path / "profiles" / "extensions"
        ext_dir.mkdir(parents=True)
        (ext_dir / "test-ext.yaml").write_text("name: test-ext\nprofile: default\n")
        d = WorkspaceDiscovery(tmp_path)
        ext = d.get_extension("test-ext")
        assert ext is not None
        assert ext.name == "test-ext"


class TestDiscoveryOverrides:
    """Tests for WorkspaceDiscovery discover_overrides() and get_override()."""

    def test_discover_overrides(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "override.yaml").write_text(
            "name: override\ndescription: Custom\nprofile: default\n"
        )
        d = WorkspaceDiscovery(tmp_path)
        overrides = d.discover_overrides()
        assert len(overrides) == 1
        assert overrides[0].name == "override"

    def test_get_override_by_name(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "custom.yaml").write_text("name: custom\nprofile: default\n")
        d = WorkspaceDiscovery(tmp_path)
        override = d.get_override("custom")
        assert override is not None
        assert override.name == "custom"


class TestDiscoveryDuplicateTools:
    """Tests for _validate_skill_duplicates (FR-011)."""

    def test_no_duplicates_no_warning(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "a.yaml").write_text(
            "name: a\nversion: 1\ntools:\n  - name: tool-a\n    handler: shell:x\n"
        )
        (s / "b.yaml").write_text(
            "name: b\nversion: 1\ntools:\n  - name: tool-b\n    handler: shell:y\n"
        )
        d = WorkspaceDiscovery(tmp_path)
        skills = d.discover_skills()
        assert len(skills) == 2

    def test_duplicate_tools_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FR-011: duplicate tool names across skills are logged as warnings."""
        s = tmp_path / "skills"
        s.mkdir()
        (s / "a.yaml").write_text(
            "name: a\nversion: 1\ntools:\n  - name: deploy\n    handler: shell:a.sh\n"
        )
        (s / "b.yaml").write_text(
            "name: b\nversion: 1\ntools:\n  - name: deploy\n    handler: shell:b.sh\n"
        )
        d = WorkspaceDiscovery(tmp_path)
        with caplog.at_level("WARNING"):
            skills = d.discover_skills()
        assert len(skills) == 2
        assert any("FR-011" in rec.message for rec in caplog.records)
        assert any("duplicate tool" in rec.message for rec in caplog.records)

    def test_discover_all_includes_extensions_overrides(self, tmp_path: Path) -> None:
        """discover_all() returns extensions and overrides alongside profiles/skills."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nname: sre\n---\n")
        ext_dir = p / "extensions"
        ext_dir.mkdir()
        (ext_dir / "oncall.yaml").write_text("name: oncall\nprofile: sre\n")
        d = WorkspaceDiscovery(tmp_path)
        entities = d.discover_all()
        assert "extensions" in entities
        assert "overrides" in entities
        assert "commands" in entities
        assert "profiles" in entities
        assert "skills" in entities


# ═══════════════════════════════════════════════════════════════════════
#  5. WorkspaceExecutor — skill tool execution
# ═══════════════════════════════════════════════════════════════════════


class TestExecutorSkillTool:
    """Tests for WorkspaceExecutor.execute_skill_tool().

    Note: execute_skill_tool is async, so tests must use ``await``.
    We use ``asyncio.run()`` since pytest-asyncio is not configured
    for this module.  Alternatively they can be marked ``@pytest.mark.asyncio``.
    """

    def _run_async(self, coro):
        """Helper to run an async coroutine synchronously."""
        return asyncio.run(coro)

    def test_tool_not_found(self, tmp_path: Path) -> None:
        profile = WorkspaceProfile(name="default")
        skill = WorkspaceSkill(
            name="test",
            version="1",
            tools=[SkillTool(name="existing", handler="shell:echo")],
        )
        exe = WorkspaceExecutor(profile, tmp_path)
        result = self._run_async(exe.execute_skill_tool(skill, "nonexistent", {}))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_tool_with_no_handler(self, tmp_path: Path) -> None:
        profile = WorkspaceProfile(name="default")
        skill = WorkspaceSkill(
            name="test",
            version="1",
            tools=[SkillTool(name="empty")],
        )
        exe = WorkspaceExecutor(profile, tmp_path)
        result = self._run_async(exe.execute_skill_tool(skill, "empty", {}))
        assert result["success"] is False
        assert "no handler" in result["error"]

    def test_unknown_handler_type(self, tmp_path: Path) -> None:
        profile = WorkspaceProfile(name="default")
        skill = WorkspaceSkill(
            name="test",
            version="1",
            tools=[SkillTool(name="weird", handler="custom:something")],
        )
        exe = WorkspaceExecutor(profile, tmp_path)
        result = self._run_async(exe.execute_skill_tool(skill, "weird", {}))
        assert result["success"] is False
        assert "Unknown handler" in result["error"]

    def test_mcp_handler_stub(self, tmp_path: Path) -> None:
        """FR-011: MCP handlers should return stub error."""
        profile = WorkspaceProfile(name="default")
        skill = WorkspaceSkill(
            name="test",
            version="1",
            tools=[SkillTool(name="dd", handler="mcp:datadog-mcp.query_logs")],
        )
        exe = WorkspaceExecutor(profile, tmp_path)
        result = self._run_async(exe.execute_skill_tool(skill, "dd", {}))
        assert result["success"] is False
        assert "MCP handler" in result["error"]
        assert "MCPProfileManager" in result["error"]


class TestExecutorCommand:
    """Tests for WorkspaceExecutor.execute_command()."""

    def test_execute_success(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "hello.sh"
        f.write_text("#!/bin/bash\necho hello")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        profile = WorkspaceProfile(name="default")
        exe = WorkspaceExecutor(profile, tmp_path)
        result = exe.execute_command(cmd, [])
        assert result["returncode"] == 0
        assert "hello" in result["stdout"]

    def test_execute_with_args(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "echo.sh"
        f.write_text('#!/bin/bash\necho "$@"')
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        profile = WorkspaceProfile(name="default")
        exe = WorkspaceExecutor(profile, tmp_path)
        result = exe.execute_command(cmd, ["hello", "world"])
        assert result["returncode"] == 0
        assert "hello world" in result["stdout"].strip()

    def test_execute_file_not_found(self, tmp_path: Path) -> None:
        cmd = WorkspaceCommand(name="nope", type="shell", path="/nonexistent.sh")
        profile = WorkspaceProfile(name="default")
        exe = WorkspaceExecutor(profile, tmp_path)
        result = exe.execute_command(cmd, [])
        assert result["returncode"] == -1
        assert "not found" in result["stderr"]

    def test_execute_timeout(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "sleep.sh"
        f.write_text("#!/bin/bash\nsleep 5")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        profile = WorkspaceProfile(name="default")
        exe = WorkspaceExecutor(profile, tmp_path)
        result = exe.execute_command(cmd, [], timeout=1)
        assert result["returncode"] == -1
        assert "timeout" in result["stderr"]


# ═══════════════════════════════════════════════════════════════════════
#  6. Helpers
# ═══════════════════════════════════════════════════════════════════════


class TestBuildShellArgs:
    """Tests for _build_shell_args() helper."""

    def test_empty_dict(self) -> None:
        assert _build_shell_args({}) == []

    def test_string_values(self) -> None:
        result = _build_shell_args({"name": "prod", "region": "us-east-1"})
        assert result == ["--name", "prod", "--region", "us-east-1"]

    def test_boolean_flags(self) -> None:
        result = _build_shell_args({"verbose": True, "dry_run": False})
        assert result == ["--verbose"]

    def test_mixed_types(self) -> None:
        result = _build_shell_args({"env": "staging", "verbose": True, "replicas": "3"})
        assert "--env" in result
        assert "staging" in result
        assert "--verbose" in result
        assert "--replicas" in result
        assert "3" in result

    def test_key_with_underscores(self) -> None:
        result = _build_shell_args({"dry_run": True})
        assert result == ["--dry-run"]


# ═══════════════════════════════════════════════════════════════════════
#  7. CLI listing functions for skills and commands
# ═══════════════════════════════════════════════════════════════════════


class TestCliSkillAndCommandListing:
    """Tests for CLI _list_skills() and _list_commands() via Workspace."""

    def test_list_skills_via_discovery(self, tmp_path: Path) -> None:
        """Skills directory is discovered and returned correctly."""
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text(
            "name: deploy\nversion: 1\ndescription: Deploy skill\n"
        )
        d = WorkspaceDiscovery(tmp_path)
        skills = d.discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "deploy"
        assert skills[0].description == "Deploy skill"

    def test_list_commands_via_discovery(self, tmp_path: Path) -> None:
        """Commands directory is discovered with executable check."""
        c = tmp_path / "commands"
        c.mkdir()
        # Executable .sh
        f1 = c / "deploy.sh"
        f1.write_text("#!/bin/bash\necho deploy")
        f1.chmod(0o755)
        # .md command (no +x needed)
        f2 = c / "backup.md"
        f2.write_text("---\nname: backup-data\ndescription: Backup\n---\n")
        d = WorkspaceDiscovery(tmp_path)
        cmds = d.discover_commands()
        assert len(cmds) == 2
        names = {cmd.name for cmd in cmds}
        assert "deploy" in names
        assert "backup-data" in names

    def test_skills_empty_output(self, tmp_path: Path) -> None:
        """Empty skills directory returns empty list."""
        s = tmp_path / "skills"
        s.mkdir()
        d = WorkspaceDiscovery(tmp_path)
        assert d.discover_skills() == []

    def test_commands_empty_output(self, tmp_path: Path) -> None:
        """Empty commands directory returns empty list."""
        c = tmp_path / "commands"
        c.mkdir()
        d = WorkspaceDiscovery(tmp_path)
        assert d.discover_commands() == []
