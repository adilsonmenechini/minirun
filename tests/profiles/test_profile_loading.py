"""Tests for profile loading, frontmatter parsing, and resolution.

Covers the full ``@sre`` / ``@datadog`` flow from file discovery through
frontmatter parsing to profile resolution by name.
"""

from __future__ import annotations

from pathlib import Path

from minirun.profiles import discover_profiles, load_profile, parse_frontmatter
from minirun.profiles.loader import list_profiles
from minirun.workspace.discovery import WorkspaceDiscovery
from minirun.workspace.models import WorkspaceProfile, WorkspaceProfileOverride

# ═══════════════════════════════════════════════════════════════════════
#  1. parse_frontmatter
# ═══════════════════════════════════════════════════════════════════════


class TestParseFrontmatter:
    """Unit tests for ``parse_frontmatter()`` — the lowest-level parser."""

    def test_parses_valid_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "profile.md"
        f.write_text(
            "---\nname: sre\ndescription: SRE specialist\nallowed_tools:\n"
            "  - http.get\n---\n# System prompt"
        )
        result = parse_frontmatter(f)
        assert result is not None
        assert result["name"] == "sre"
        assert result["description"] == "SRE specialist"
        assert "http.get" in result["allowed_tools"]

    def test_returns_none_when_no_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "plain.md"
        f.write_text("# Just a heading\nNo frontmatter here.")
        assert parse_frontmatter(f) is None

    def test_returns_none_with_only_opening_delimiter(self, tmp_path: Path) -> None:
        f = tmp_path / "partial.md"
        f.write_text("---\nname: partial")
        assert parse_frontmatter(f) is None

    def test_returns_none_on_malformed_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.md"
        f.write_text("---\nkey: [unclosed list\n---\nrest")
        result = parse_frontmatter(f)
        # Malformed YAML should be caught and return None
        assert result is None

    def test_returns_none_on_non_dict_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "array.md"
        f.write_text("---\n- item1\n- item2\n---\ncontent")
        assert parse_frontmatter(f) is None

    def test_returns_none_on_nonexistent_file(self, tmp_path: Path) -> None:
        result = parse_frontmatter(tmp_path / "nonexistent.md")
        assert result is None

    def test_parses_datadog_like_frontmatter(self, tmp_path: Path) -> None:
        """Real-world frontmatter matching workspace/profiles/datadog.md."""
        content = (
            "---\n"
            'name: "datadog"\n'
            'description: "Datadog SRE specialist"\n'
            "allowed_tools:\n"
            "  - datadog-mcp.query_logs\n"
            "  - datadog-mcp.query_metrics\n"
            "mcp_servers:\n"
            "  datadog-mcp:\n"
            "    transport: stdio\n"
            '    command: "npx"\n'
            "    args:\n"
            '      - "-y"\n'
            '      - "@datadog/mcp-server"\n'
            "    env:\n"
            '      DATADOG_API_KEY: "${DATADOG_API_KEY}"\n'
            "---\n"
            "# Datadog SRE\n"
        )
        f = tmp_path / "datadog.md"
        f.write_text(content)
        result = parse_frontmatter(f)
        assert result is not None
        assert result["name"] == "datadog"
        assert "datadog-mcp.query_logs" in result["allowed_tools"]
        assert "mcp_servers" in result
        servers = result["mcp_servers"]
        assert "datadog-mcp" in servers
        assert servers["datadog-mcp"]["command"] == "npx"


# ═══════════════════════════════════════════════════════════════════════
#  2. discover_profiles
# ═══════════════════════════════════════════════════════════════════════


class TestDiscoverProfiles:
    """Tests for ``discover_profiles()`` in different formats and scenarios."""

    MINIMAL_YAML = "name: test\nprovider: openai\n"

    def test_empty_when_no_dir(self, tmp_path: Path) -> None:
        assert discover_profiles(tmp_path / "nonexistent") == []

    def test_empty_when_empty_dir(self, tmp_path: Path) -> None:
        (tmp_path / "agents").mkdir()
        assert discover_profiles(tmp_path / "agents") == []

    def test_yaml_profiles(self, tmp_path: Path) -> None:
        d = tmp_path / "agents"
        d.mkdir()
        (d / "sre.yaml").write_text(self.MINIMAL_YAML)
        (d / "ops.yml").write_text("name: ops\n")
        profiles = discover_profiles(d)
        assert len(profiles) == 2
        names = {p["name"] for p in profiles}
        assert names == {"sre", "ops"}

    def test_md_profiles(self, tmp_path: Path) -> None:
        d = tmp_path / "agents"
        d.mkdir()
        (d / "datadog.md").write_text(
            "---\nname: datadog\ndescription: Datadog specialist\n---\n# Content"
        )
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "datadog"
        assert profiles[0]["format"] == "md"
        assert profiles[0]["description"] == "Datadog specialist"

    def test_md_profiles_without_frontmatter(self, tmp_path: Path) -> None:
        """MD file without frontmatter uses filename stem as name."""
        d = tmp_path / "agents"
        d.mkdir()
        (d / "sre.md").write_text("# SRE profile")
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "sre"
        assert profiles[0]["description"] == ""

    def test_skips_invalid_yaml(self, tmp_path: Path) -> None:
        d = tmp_path / "agents"
        d.mkdir()
        (d / "good.yaml").write_text(self.MINIMAL_YAML)
        (d / "bad.yaml").write_text("key: [unclosed")
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "good"

    def test_mixed_yaml_and_md(self, tmp_path: Path) -> None:
        """Discover both .yaml and .md profiles in the same directory."""
        d = tmp_path / "agents"
        d.mkdir()
        (d / "default.yaml").write_text("name: default\n")
        (d / "datadog.md").write_text("---\nname: datadog\n---\n# Datadog profile")
        (d / "ignored.txt").write_text("ignored")
        profiles = discover_profiles(d)
        assert len(profiles) == 2
        names = {p["name"] for p in profiles}
        assert names == {"default", "datadog"}

    def test_directory_based_profile_yaml(self, tmp_path: Path) -> None:
        """Subdirectory with PROFILE.yaml is discovered."""
        d = tmp_path / "agents"
        d.mkdir()
        sre_dir = d / "sre"
        sre_dir.mkdir()
        (sre_dir / "PROFILE.yaml").write_text("name: sre\n")
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "sre"
        assert profiles[0]["format"] == "yaml"

    def test_directory_based_profile_md(self, tmp_path: Path) -> None:
        """Subdirectory with PROFILE.md is discovered and frontmatter parsed."""
        d = tmp_path / "agents"
        d.mkdir()
        sre_dir = d / "sre"
        sre_dir.mkdir()
        (sre_dir / "PROFILE.md").write_text(
            "---\nname: sre\ndescription: SRE profile\n---\n# Content"
        )
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "sre"
        assert profiles[0]["description"] == "SRE profile"


# ═══════════════════════════════════════════════════════════════════════
#  3. load_profile
# ═══════════════════════════════════════════════════════════════════════


class TestLoadProfile:
    """Tests for ``load_profile()``."""

    def test_load_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "sre.yaml"
        f.write_text("name: sre\nprovider: openai\n")
        result = load_profile(str(f))
        assert result is not None
        assert result["name"] == "sre"
        assert result["format"] == "yaml"

    def test_load_md_with_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "datadog.md"
        f.write_text(
            "---\nname: datadog\ndescription: Datadog specialist\n---\n# Content"
        )
        result = load_profile(str(f))
        assert result is not None
        assert result["name"] == "datadog"
        assert result["description"] == "Datadog specialist"
        assert result["format"] == "md"

    def test_load_md_without_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "sre.md"
        f.write_text("# SRE profile")
        result = load_profile(str(f))
        assert result is not None
        assert result["name"] == "sre"
        assert result["format"] == "md"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        result = load_profile(str(tmp_path / "nonexistent.yaml"))
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
#  4. list_profiles (combinação builtin + workspace)
# ═══════════════════════════════════════════════════════════════════════


class TestListProfiles:
    """Tests for ``list_profiles()`` — builtin + workspace merge with precedence."""

    def test_empty_when_no_dirs(self, tmp_path: Path) -> None:
        assert list_profiles() == []

    def test_builtin_only(self, tmp_path: Path) -> None:
        d = tmp_path / "builtin"
        d.mkdir()
        (d / "default.yaml").write_text("name: default\n")
        profiles = list_profiles(builtin_agents_dir=d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "default"

    def test_workspace_overrides_builtin(self, tmp_path: Path) -> None:
        """Workspace profile with same name takes precedence.

        Note: discover_profiles() for .yaml files uses filename stem as name
        and does not parse frontmatter for description. Workspace wins by
        overwriting the dict entry.
        """
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        (builtin / "sre.yaml").write_text("name: sre\n")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "sre.yaml").write_text("name: sre\ndescription: workspace\n")

        profiles = list_profiles(
            builtin_agents_dir=builtin, workspace_agents_dir=workspace
        )
        # Both have name "sre" → workspace overwrites builtin
        # desc is empty because .yaml discovery uses entry.stem + ""
        assert len(profiles) == 1
        assert profiles[0]["name"] == "sre"

    def test_merge_distinct_names(self, tmp_path: Path) -> None:
        """Profiles with distinct names from both dirs are combined."""
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        (builtin / "default.yaml").write_text("name: default\n")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "custom.yaml").write_text("name: custom\n")

        profiles = list_profiles(
            builtin_agents_dir=builtin, workspace_agents_dir=workspace
        )
        assert len(profiles) == 2
        names = {p["name"] for p in profiles}
        assert names == {"default", "custom"}

    def test_ignores_nonexistent_dirs(self, tmp_path: Path) -> None:
        profiles = list_profiles(
            builtin_agents_dir=tmp_path / "nonexistent",
            workspace_agents_dir=tmp_path / "also-nonexistent",
        )
        assert profiles == []


# ═══════════════════════════════════════════════════════════════════════
#  5. WorkspaceProfile.from_file — parsing real-world datadog.md
# ═══════════════════════════════════════════════════════════════════════


class TestWorkspaceProfileRealWorld:
    """Tests mirroring the real workspace/profiles/datadog.md and terraform.md."""

    DATADOG_MD = """---
name: datadog
description: Datadog SRE specialist
allowed_tools:
  - filesystem.read
  - filesystem.grep
  - datadog-mcp.query_logs
  - datadog-mcp.query_metrics
mcp_servers:
  datadog-mcp:
    transport: stdio
    command: npx
    args:
      - "-y"
      - "@datadog/mcp-server"
    env:
      DATADOG_API_KEY: "${DATADOG_API_KEY}"
      DATADOG_APP_KEY: "${DATADOG_APP_KEY}"
      DD_SITE: "${DD_SITE:-datadoghq.com}"
---
# Datadog SRE — Incident Response Specialist

You are a Datadog SRE specialist.
"""

    def test_parses_datadog_profile(self, tmp_path: Path) -> None:
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "datadog.md").write_text(self.DATADOG_MD)
        profile = WorkspaceProfile.from_file(p / "datadog.md")

        # Core fields
        assert profile.name == "datadog"
        assert profile.description == "Datadog SRE specialist"
        assert "Datadog SRE" in profile.system_prompt

        # allowed_tools
        assert "filesystem.read" in profile.allowed_tools
        assert "datadog-mcp.query_logs" in profile.allowed_tools
        assert "datadog-mcp.query_metrics" in profile.allowed_tools
        assert len(profile.allowed_tools) == 4

        # MCP servers
        assert len(profile.mcp_servers) == 1
        server = profile.mcp_servers[0]
        assert server.name == "datadog-mcp"
        assert server.transport == "stdio"
        assert server.command == "npx"
        assert server.args == ["-y", "@datadog/mcp-server"]
        assert server.host is None
        assert server.port is None

        # Environment variables (preserved as-is — substitution at runtime)
        assert server.env is not None
        assert server.env["DATADOG_API_KEY"] == "${DATADOG_API_KEY}"
        assert server.env["DD_SITE"] == "${DD_SITE:-datadoghq.com}"

    def test_parses_terraform_profile(self, tmp_path: Path) -> None:
        """Real-world terraform profile with different MCP server format."""
        content = (
            "---\n"
            'name: "terraform"\n'
            'description: "Terraform IaC reviewer"\n'
            "allowed_tools:\n"
            "  - filesystem.read\n"
            "  - terraform-mcp.parse_plan\n"
            "  - terraform-mcp.analyze_changes\n"
            "mcp_servers:\n"
            "  terraform-mcp:\n"
            "    transport: stdio\n"
            '    command: "python3"\n'
            "    args:\n"
            '      - "-m"\n'
            "      - terraform_mcp_server\n"
            "---\n"
            "# Terraform Workflow Assistant"
        )
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "terraform.md").write_text(content)
        profile = WorkspaceProfile.from_file(p / "terraform.md")

        assert profile.name == "terraform"
        assert len(profile.mcp_servers) == 1
        server = profile.mcp_servers[0]
        assert server.name == "terraform-mcp"
        assert server.command == "python3"
        assert server.args == ["-m", "terraform_mcp_server"]

    def test_profile_with_no_mcp_servers(self, tmp_path: Path) -> None:
        """Profile without mcp_servers defaults to empty list."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "simple.md").write_text(
            "---\nname: helper\ndescription: Helper\n"
            "allowed_tools:\n  - filesystem.read\n---\n# Helper"
        )
        profile = WorkspaceProfile.from_file(p / "simple.md")
        assert profile.mcp_servers == []
        assert profile.allowed_tools == ["filesystem.read"]

    def test_profile_with_list_of_mcp_servers(self, tmp_path: Path) -> None:
        """MCP servers can be specified as a list of dicts."""
        content = (
            "---\n"
            "name: multi\n"
            "mcp_servers:\n"
            "  - name: server-a\n"
            "    transport: stdio\n"
            '    command: "cmd-a"\n'
            "  - name: server-b\n"
            "    transport: stdio\n"
            '    command: "cmd-b"\n'
            "---\n"
            "# Multi-server profile"
        )
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "multi.md").write_text(content)
        profile = WorkspaceProfile.from_file(p / "multi.md")
        assert len(profile.mcp_servers) == 2
        assert profile.mcp_servers[0].name == "server-a"
        assert profile.mcp_servers[1].name == "server-b"

    def test_profile_missing_name_uses_filename(self, tmp_path: Path) -> None:
        """When name is missing from frontmatter, filename stem is used."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nallowed_tools:\n  - http.get\n---\n# SRE")
        profile = WorkspaceProfile.from_file(p / "sre.md")
        assert profile.name == "sre"


# ═══════════════════════════════════════════════════════════════════════
#  6. Resolução de profile por nome (@sre → get_profile)
# ═══════════════════════════════════════════════════════════════════════


class TestProfileResolution:
    """Tests for resolving profiles by name — the ``@sre`` flow."""

    def test_get_profile_by_name(self, tmp_path: Path) -> None:
        """WorkspaceDiscovery.get_profile() resolves name → WorkspaceProfile."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\nname: sre\ndescription: SRE specialist\n"
            "allowed_tools:\n  - datadog-mcp.query_logs\n"
            "mcp_servers:\n"
            "  dd:\n"
            "    transport: stdio\n"
            "    command: datadog-mcp\n"
            "---\n# SRE System Prompt"
        )
        d = WorkspaceDiscovery(tmp_path)
        profile = d.get_profile("sre")

        assert profile is not None
        assert profile.name == "sre"
        assert profile.description == "SRE specialist"
        assert "datadog-mcp.query_logs" in profile.allowed_tools
        assert len(profile.mcp_servers) == 1

    def test_get_profile_nonexistent(self, tmp_path: Path) -> None:
        d = WorkspaceDiscovery(tmp_path)
        assert d.get_profile("nonexistent") is None

    def test_get_profile_case_sensitive(self, tmp_path: Path) -> None:
        """Profile name resolution is case-sensitive.

        Uses distinct filenames to avoid filesystem case collisions
        (macOS APFS case-insensitive by default).
        """
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "profile-a.md").write_text("---\nname: SRE\n---\n# Content")
        (p / "profile-b.md").write_text("---\nname: sre\n---\n# Content")
        d = WorkspaceDiscovery(tmp_path)
        assert d.get_profile("SRE") is not None
        assert d.get_profile("sre") is not None
        assert d.get_profile("Sre") is None

    def test_get_profile_among_multiple(self, tmp_path: Path) -> None:
        """Resolve one profile among several in the same directory."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "datadog.md").write_text("---\nname: datadog\n---\n# Datadog\n")
        (p / "terraform.md").write_text("---\nname: terraform\n---\n# Terraform\n")
        (p / "sre.md").write_text("---\nname: sre\n---\n# SRE\n")
        d = WorkspaceDiscovery(tmp_path)
        profile = d.get_profile("terraform")
        assert profile is not None
        assert profile.name == "terraform"

    def test_discover_all_includes_profiles(self, tmp_path: Path) -> None:
        """discover_all() returns profiles alongside other entities."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nname: sre\n---\n# Content")
        d = WorkspaceDiscovery(tmp_path)
        entities = d.discover_all()
        assert "profiles" in entities
        assert len(entities["profiles"]) == 1
        assert entities["profiles"][0].name == "sre"


# ═══════════════════════════════════════════════════════════════════════
#  7. Profile Extensions (apply_extensions)
# ═══════════════════════════════════════════════════════════════════════


class TestProfileExtensions:
    """Tests for ``apply_extensions()`` — merging extensions into a profile."""

    def test_merge_instructions(self, tmp_path: Path) -> None:
        """Extension instructions are appended to system_prompt."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nname: sre\n---\n# SRE Profile")
        profile = WorkspaceProfile.from_file(p / "sre.md")

        ext = WorkspaceProfileOverride(
            name="oncall",
            profile="sre",
            instructions="Follow on-call escalation procedures.",
        )
        merged = profile.apply_extensions([ext])
        assert "on-call escalation" in merged.system_prompt
        assert "# SRE Profile" in merged.system_prompt

    def test_merge_allowed_tools(self, tmp_path: Path) -> None:
        """Extension allowed_tools are appended and deduplicated."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\nname: sre\nallowed_tools:\n  - filesystem.read\n---\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")

        ext = WorkspaceProfileOverride(
            name="oncall",
            profile="sre",
            allowed_tools=[
                "filesystem.read",  # duplicate — should be ignored
                "datadog-mcp.get_incident",
            ],
        )
        merged = profile.apply_extensions([ext])
        assert merged.allowed_tools == [
            "filesystem.read",
            "datadog-mcp.get_incident",
        ]

    def test_skips_unrelated_extensions(self, tmp_path: Path) -> None:
        """Extension targeting a different profile is skipped."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nname: sre\n---\n# SRE")
        profile = WorkspaceProfile.from_file(p / "sre.md")

        ext = WorkspaceProfileOverride(
            name="pm", profile="project-manager", instructions="Manage projects"
        )
        merged = profile.apply_extensions([ext])
        # No change since extension targets a different profile
        assert merged.system_prompt == "# SRE"

    def test_returns_new_instance(self, tmp_path: Path) -> None:
        """apply_extensions() returns a new profile; original is unchanged."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nname: sre\n---\n")
        profile = WorkspaceProfile.from_file(p / "sre.md")

        ext = WorkspaceProfileOverride(
            name="oncall",
            profile="sre",
            instructions="On-call instructions",
        )
        merged = profile.apply_extensions([ext])
        assert merged is not profile  # different object
        assert merged.system_prompt != profile.system_prompt

    def test_multiple_extensions_same_profile(self, tmp_path: Path) -> None:
        """Multiple extensions for the same profile are all applied."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text(
            "---\nname: sre\nallowed_tools:\n  - filesystem.read\n---\n"
        )
        profile = WorkspaceProfile.from_file(p / "sre.md")

        exts = [
            WorkspaceProfileOverride(
                name="oncall-a",
                profile="sre",
                instructions="On-call level 1",
                allowed_tools=["datadog-mcp.get_incident"],
            ),
            WorkspaceProfileOverride(
                name="oncall-b",
                profile="sre",
                instructions="On-call level 2",
                allowed_tools=["pagerduty-mcp.acknowledge"],
            ),
        ]
        merged = profile.apply_extensions(exts)
        assert "On-call level 1" in merged.system_prompt
        assert "On-call level 2" in merged.system_prompt
        assert "datadog-mcp.get_incident" in merged.allowed_tools
        assert "pagerduty-mcp.acknowledge" in merged.allowed_tools
        assert len(merged.allowed_tools) == 3  # filesystem.read + 2 new


# ═══════════════════════════════════════════════════════════════════════
#  8. Edge Cases
# ═══════════════════════════════════════════════════════════════════════


class TestProfileEdgeCases:
    """Edge cases across all profile loading functions."""

    def test_empty_yaml_file(self, tmp_path: Path) -> None:
        d = tmp_path / "agents"
        d.mkdir()
        (d / "empty.yaml").write_text("")
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "empty"

    def test_yaml_with_only_comments(self, tmp_path: Path) -> None:
        """YAML with only comments is syntactically valid and discovered.

        Content validation happens at load time via :meth:`from_file`;
        discovery only checks syntax.
        """
        d = tmp_path / "agents"
        d.mkdir()
        (d / "comments.yaml").write_text("# just a comment")
        profiles = discover_profiles(d)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "comments"

    def test_directory_based_no_manifest(self, tmp_path: Path) -> None:
        """Subdirectory without PROFILE.* is ignored."""
        d = tmp_path / "agents"
        d.mkdir()
        sre_dir = d / "sre"
        sre_dir.mkdir()
        (sre_dir / "config.yaml").write_text("key: val")
        profiles = discover_profiles(d)
        assert profiles == []

    def test_md_with_only_frontmatter_dashes(self, tmp_path: Path) -> None:
        """Markdown consisting solely of frontmatter."""
        p = tmp_path / "profiles"
        p.mkdir()
        (p / "sre.md").write_text("---\nname: sre\n---\n")
        profile = WorkspaceProfile.from_file(p / "sre.md")
        assert profile.name == "sre"
        assert profile.system_prompt == ""
