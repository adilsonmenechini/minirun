from __future__ import annotations

from pathlib import Path

import pytest

from minirun.workspace.models import (
    MCPServerConfig,
    WorkspaceProfile,
    WorkspaceProfileOverride,
    WorkspaceSkill,
)

# ── MCPServerConfig ──────────────────────────────────────────────────


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


# ── WorkspaceProfile from_markdown ───────────────────────────────────


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


# ── WorkspaceProfile env substitution ────────────────────────────────


class TestWorkspaceProfileEnvSubstitution:
    def test_env_substitutes_in_mcp_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DD_TOKEN", "secret-123")
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\n"
            "name: sre\n"
            "mcp_servers:\n"
            "  dd:\n"
            "    transport: stdio\n"
            "    command: dd-mcp --token ${DD_TOKEN}\n"
            "---\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")
        assert profile.mcp_servers[0].command == "dd-mcp --token ${DD_TOKEN}"

    def test_missing_env_keeps_placeholder(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\nname: sre\nmcp_servers:\n  x:\n    command: x ${MISSING_VAR}\n---\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")
        assert profile.mcp_servers[0].command == "x ${MISSING_VAR}"


# ── WorkspaceSkill ───────────────────────────────────────────────────


class TestWorkspaceSkill:
    def test_from_file(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "deploy.yaml").write_text(
            "name: deploy\n"
            "version: 1\n"
            "description: Deploy skill\n"
            "tools:\n"
            "  - name: deploy.sh\n"
            "    entrypoint: deploy.sh\n"
        )
        skill = WorkspaceSkill.from_file(s / "deploy.yaml")
        assert skill.name == "deploy"
        assert skill.version == 1
        assert len(skill.tools) == 1
        assert skill.tools[0].name == "deploy.sh"

    def test_default_values(self, tmp_path: Path) -> None:
        s = tmp_path / "skills"
        s.mkdir()
        (s / "x.yaml").write_text("name: x\nversion: 1\n")
        skill = WorkspaceSkill.from_file(s / "x.yaml")
        assert skill.tools == []


# ── WorkspaceProfileOverride ─────────────────────────────────────────


class TestWorkspaceProfileOverride:
    def test_from_file(self, tmp_path: Path) -> None:
        o = tmp_path / "overrides"
        o.mkdir()
        (o / "pm.yaml").write_text(
            "name: pm\n"
            "description: Project Manager\n"
            "profile: default\n"
            "instructions: Manage the project\n"
        )
        override = WorkspaceProfileOverride.from_file(o / "pm.yaml")
        assert override.name == "pm"
        assert override.description == "Project Manager"
        assert override.profile == "default"
        assert override.instructions == "Manage the project"
