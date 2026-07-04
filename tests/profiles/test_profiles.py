from __future__ import annotations

from pathlib import Path

from minirun.profiles import discover_profiles, load_profile


class TestDiscoverProfiles:
    def test_empty_when_no_agents_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "nonexistent"
        profiles = discover_profiles(empty)
        assert profiles == []

    def test_empty_when_no_files(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        profiles = discover_profiles(agents)
        assert profiles == []

    def test_discovers_yaml_profiles(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "default.yaml").write_text("provider: openai")
        (agents / "custom.yml").write_text("provider: anthropic")

        profiles = discover_profiles(agents)
        names = [p["name"] for p in profiles]
        assert "default" in names
        assert "custom" in names
        assert len(profiles) == 2

    def test_discovers_md_profiles(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "assistant.md").write_text("# Assistant")

        profiles = discover_profiles(agents)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "assistant"
        assert profiles[0]["format"] == "md"

    def test_ignores_unknown_extensions(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "profile.yaml").write_text("key: val")
        (agents / "notes.txt").write_text("ignored")

        profiles = discover_profiles(agents)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "profile"


class TestLoadProfile:
    def test_load_existing_profile(self, tmp_path: Path) -> None:
        profile_file = tmp_path / "sre.yaml"
        profile_file.write_text("name: sre\nprovider: openai\n")
        result = load_profile(str(profile_file))
        assert result is not None
        assert result["name"] == "sre"
        assert result["format"] == "yaml"

    def test_load_missing_profile(self, tmp_path: Path) -> None:
        result = load_profile(str(tmp_path / "nonexistent.yaml"))
        assert result is None

    def test_load_md_profile(self, tmp_path: Path) -> None:
        profile_file = tmp_path / "helper.md"
        profile_file.write_text("# helper")
        result = load_profile(str(profile_file))
        assert result is not None
        assert result["name"] == "helper"
        assert result["format"] == "md"
