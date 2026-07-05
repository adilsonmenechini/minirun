from __future__ import annotations

from pathlib import Path

import pytest

from minirun.workspace.discovery import WorkspaceDiscovery
from minirun.workspace.executor import WorkspaceExecutor
from minirun.workspace.models import (
    MCPServerConfig,
    WorkspaceCommand,
    WorkspaceProfile,
    WorkspaceProfileOverride,
    WorkspaceSkill,
)


class TestMCPServerConfig:
    def test_stdio_defaults(self) -> None:
        srv = MCPServerConfig(name="dd", transport="stdio", command="dd-mcp")
        assert srv.name == "dd"
        assert srv.transport == "stdio"
        assert srv.command == "dd-mcp"
        assert srv.args is None
        assert srv.env is None
        assert srv.host is None
        assert srv.port is None

    def test_tcp_requires_host_port(self) -> None:
        srv = MCPServerConfig(name="tf", transport="tcp", host="127.0.0.1", port=4444)
        assert srv.host == "127.0.0.1"
        assert srv.port == 4444


class TestWorkspaceProfileMarkdown:
    def test_from_file_frontmatter(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\nname: sre\nallowed_tools:\n  - http.get\n---\n# SRE Profile\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")
        assert profile.name == "sre"
        assert profile.system_prompt == "# SRE Profile"
        assert "http.get" in profile.allowed_tools
        assert profile.mcp_servers == []

    def test_from_file_with_mcp_servers(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\n"
            "name: sre\n"
            "mcp_servers:\n"
            "  dd:\n"
            "    transport: stdio\n"
            "    command: datadog-mcp\n"
            "---\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")
        assert profile.name == "sre"
        assert len(profile.mcp_servers) == 1
        assert profile.mcp_servers[0].name == "dd"
        assert profile.mcp_servers[0].command == "datadog-mcp"

    def test_no_frontmatter_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "plain.md").write_text("no frontmatter")
        with pytest.raises(ValueError, match="missing frontmatter"):
            WorkspaceProfile.from_file(p / "plain.md")


class TestWorkspaceSkill:
    def test_from_file(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text(
            "name: deploy\nversion: 1.0.0\ndescription: Deploy skill\n"
            "tools:\n  - name: deploy.sh\n    entrypoint: deploy.sh\n"
        )
        skill = WorkspaceSkill.from_file(s / "deploy.yaml")
        assert skill.name == "deploy"
        assert skill.version == "1.0.0"
        assert len(skill.tools) == 1
        assert skill.tools[0].name == "deploy.sh"

    def test_default_values(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "x.yaml").write_text("name: x\nversion: 1\n")
        skill = WorkspaceSkill.from_file(s / "x.yaml")
        assert skill.tools == []


class TestWorkspaceProfileOverride:
    def test_from_file(self, tmp_path: Path) -> None:
        o = tmp_path / "overrides"
        o.mkdir()
        (o / "pm.yaml").write_text(
            "name: pm\ndescription: Project Manager\n"
            "profile: default\ninstructions: Manage the project\n"
        )
        override = WorkspaceProfileOverride.from_file(o / "pm.yaml")
        assert override.name == "pm"
        assert override.description == "Project Manager"
        assert override.profile == "default"
        assert override.instructions == "Manage the project"


class TestWorkspaceCommand:
    def test_from_file_sh(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "deploy.sh"
        f.write_text("#!/bin/bash\necho deploy")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "deploy"
        assert cmd.type == "shell"
        assert cmd.path == str(f)

    def test_from_file_md(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "sync.md"
        f.write_text(
            "---\n"
            "name: sync-data\n"
            "description: Sync data from source to destination\n"
            "type: shell\n"
            "---\n"
            "```sh\necho syncing\n```"
        )
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "sync-data"
        assert cmd.description == "Sync data from source to destination"
        assert cmd.type == "shell"
        assert cmd.path == str(f)

    def test_from_file_md_fallback_no_frontmatter(self, tmp_path: Path) -> None:
        """.md without frontmatter falls back to filename stem."""
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "script.md"
        f.write_text("# Just a script description\n")
        cmd = WorkspaceCommand.from_file(f)
        assert cmd.name == "script"
        assert cmd.type == "shell"


class TestWorkspaceDiscovery:
    def test_discover_profiles_empty(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.discover_profiles() == []

    def test_discover_profiles_single(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "default.md").write_text("---\nname: default\n---\n")
        d = WorkspaceDiscovery(tmp_path)
        profiles = d.discover_profiles()
        assert len(profiles) == 1
        assert profiles[0].name == "default"

    def test_discover_skills(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text("name: deploy\nversion: 1\n")
        d = WorkspaceDiscovery(tmp_path)
        skills = d.discover_skills()
        assert len(skills) == 1
        assert skills[0].name == "deploy"

    def test_discover_commands(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "hello.sh"
        f.write_text("#!/bin/bash\necho hi")
        f.chmod(0o755)
        d = WorkspaceDiscovery(tmp_path)
        cmds = d.discover_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "hello"
        assert cmds[0].type == "shell"

    def test_discover_commands_md(self, tmp_path: Path) -> None:
        """.md command files are discovered and parsed for frontmatter."""
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "backup.md"
        f.write_text(
            "---\nname: backup-data\ndescription: Backup database\ntype: shell\n"
            "---\n```sh\necho backup\n```"
        )
        d = WorkspaceDiscovery(tmp_path)
        cmds = d.discover_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "backup-data"
        assert cmds[0].description == "Backup database"

    def test_get_profile(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "default.md").write_text("---\nname: default\n---\n")
        d = WorkspaceDiscovery(tmp_path)
        assert d.get_profile("default") is not None
        assert d.get_profile("nonexistent") is None

    def test_discover_all(self, tmp_path: Path) -> None:
        (tmp_path / "profiles").mkdir()
        (tmp_path / "profiles" / "p.md").write_text("---\nname: p\n---\n")
        d = WorkspaceDiscovery(tmp_path)
        all_entities = d.discover_all()
        assert "profiles" in all_entities
        assert len(all_entities["profiles"]) == 1

    def test_malformed_profile_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "bad.md").write_text("---\ninvalid: :\n---\n")
        d = WorkspaceDiscovery(tmp_path)
        profiles = d.discover_profiles()
        assert profiles == []


class TestWorkspaceExecutor:
    def test_execute_command_success(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "hello.sh"
        f.write_text("#!/bin/bash\necho hello")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        exe = WorkspaceExecutor(tmp_path)
        result = exe.execute_command(cmd, [])
        assert result["returncode"] == 0
        assert "hello" in result["stdout"]

    def test_execute_command_missing(self, tmp_path: Path) -> None:
        exe = WorkspaceExecutor(tmp_path)
        result = exe.execute_command(
            WorkspaceCommand(name="nope", type="shell", path="does-not-exist-sh"),
            [],
        )
        assert result["returncode"] == -1
        assert "not found" in result["stderr"]

    def test_execute_command_timeout(self, tmp_path: Path) -> None:
        c = tmp_path / "commands"
        c.mkdir()
        f = c / "sleep.sh"
        f.write_text("#!/bin/bash\nsleep 5")
        f.chmod(0o755)
        cmd = WorkspaceCommand.from_file(f)
        exe = WorkspaceExecutor(tmp_path)
        result = exe.execute_command(cmd, [], timeout=2)
        assert result["returncode"] == -1
        assert "timeout" in result["stderr"]

    def test_agent_execution_stub(self, tmp_path: Path) -> None:
        exe = WorkspaceExecutor(tmp_path)
        override = WorkspaceProfileOverride(name="a", profile="default")
        result = exe.execute_override(override, {"task": "x"})
        assert result["status"] == "not_implemented"


class TestMCPProfileManagerSubstitution:
    def test_connect_substitutes_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DD_TOKEN", "secret-123")
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\nname: sre\nmcp_servers:\n  dd:\n"
            "    transport: tcp\n    host: 127.0.0.1\n    port: 4444\n---\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")
        from minirun.workspace.mcp_manager import MCPProfileManager

        mgr = MCPProfileManager(profile)
        assert len(mgr.profile.mcp_servers) == 1
        cfg = mgr._convert_server_config(mgr.profile.mcp_servers[0])
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 4444
