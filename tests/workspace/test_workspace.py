from __future__ import annotations

from pathlib import Path

from minirun.workspace import Workspace


class TestWorkspaceInit:
    def test_init_creates_subdirectories(self, tmp_path: Path) -> None:
        ws = Workspace(str(tmp_path))
        ws.init()

        assert (tmp_path / "memory").is_dir()
        assert (tmp_path / "profiles").is_dir()
        assert (tmp_path / "commands").is_dir()
        assert (tmp_path / "skills").is_dir()

    def test_init_is_idempotent(self, tmp_path: Path) -> None:
        ws = Workspace(str(tmp_path))
        ws.init()
        ws.init()  # second call should not raise

        assert (tmp_path / "memory").is_dir()

    def test_init_reports_created(self, tmp_path: Path) -> None:
        ws = Workspace(str(tmp_path))
        result = ws.init()
        assert result is True

    def test_init_existing_returns_false(self, tmp_path: Path) -> None:
        for subdir in ["memory", "profiles", "commands", "skills"]:
            (tmp_path / subdir).mkdir(parents=True)
        ws = Workspace(str(tmp_path))
        result = ws.init()
        assert result is False


class TestWorkspaceProfileDiscovery:
    def test_discover_profiles_empty(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        ws = Workspace(str(tmp_path))
        profiles = ws.discover_profiles()
        assert profiles == []

    def test_discover_yaml_profiles(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "default.yaml").write_text("provider: openai")
        (profiles_dir / "custom.yaml").write_text("provider: anthropic")

        ws = Workspace(str(tmp_path))
        profiles = ws.discover_profiles()

        names = [p["name"] for p in profiles]
        assert "default" in names
        assert "custom" in names
        assert len(profiles) == 2

    def test_discover_md_profiles(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "assistant.md").write_text("# Assistant")

        ws = Workspace(str(tmp_path))
        profiles = ws.discover_profiles()

        assert len(profiles) == 1
        assert profiles[0]["name"] == "assistant"
        assert profiles[0]["format"] == "md"

    def test_discover_md_profiles_frontmatter(self, tmp_path: Path) -> None:
        """Profiles with frontmatter use name/description from frontmatter."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profile-a.md").write_text(
            "---\nname: my-profile\ndescription: My profile description"
            "\n---\n# System prompt"
        )

        ws = Workspace(str(tmp_path))
        profiles = ws.discover_profiles()

        assert len(profiles) == 1
        assert profiles[0]["name"] == "my-profile"
        assert profiles[0]["description"] == "My profile description"


class TestWorkspaceSkillDiscovery:
    def test_discover_skills_empty(self, tmp_path: Path) -> None:
        ws = Workspace(str(tmp_path))
        skills = ws.discover_skills()
        assert skills == []

    def test_discover_skills_finds_md_and_yaml(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "code-review.md").write_text("# Code Review")
        (skills_dir / "deploy.yaml").write_text("name: deploy")
        (skills_dir / "ignored.txt").write_text("should be ignored")

        ws = Workspace(str(tmp_path))
        skills = ws.discover_skills()

        names = [s["name"] for s in skills]
        assert "code-review" in names
        assert "deploy" in names
        assert "ignored" not in names
        assert len(skills) == 2

    def test_discover_skills_frontmatter(self, tmp_path: Path) -> None:
        """Skills with .md frontmatter use name/description from frontmatter."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my-skill.md").write_text(
            "---\nname: k8s-debug\ndescription: Debug Kubernetes workloads"
            "\n---\n# Skill content"
        )

        ws = Workspace(str(tmp_path))
        skills = ws.discover_skills()

        assert len(skills) == 1
        assert skills[0]["name"] == "k8s-debug"
        assert skills[0]["description"] == "Debug Kubernetes workloads"


class TestWorkspaceCommandDiscovery:
    def test_discover_commands_empty(self, tmp_path: Path) -> None:
        ws = Workspace(str(tmp_path))
        commands = ws.discover_commands()
        assert commands == []

    def test_discover_commands_finds_md_sh_and_py(self, tmp_path: Path) -> None:
        commands_dir = tmp_path / "commands"
        commands_dir.mkdir()
        # .md with frontmatter
        (commands_dir / "deploy.md").write_text(
            "---\nname: deploy\ndescription: Deploy to production\n---\n# Deploy"
        )
        # .py without frontmatter
        (commands_dir / "build.py").write_text("print('build')")
        # .sh without frontmatter
        (commands_dir / "cleanup.sh").write_text("echo cleanup")
        # .txt should be ignored
        (commands_dir / "readme.txt").write_text("should be ignored")

        ws = Workspace(str(tmp_path))
        commands = ws.discover_commands()

        names = [c["name"] for c in commands]
        assert "deploy" in names
        assert "build" in names
        assert "cleanup" in names
        assert "readme" not in names
        assert len(commands) == 3

    def test_discover_commands_frontmatter(self, tmp_path: Path) -> None:
        """Commands with .md frontmatter use name/description from frontmatter."""
        commands_dir = tmp_path / "commands"
        commands_dir.mkdir()
        (commands_dir / "my-cmd.md").write_text(
            "---\nname: my-command\ndescription: My custom command"
            "\n---\n```sh\necho hi\n```"
        )

        ws = Workspace(str(tmp_path))
        commands = ws.discover_commands()

        assert len(commands) == 1
        assert commands[0]["name"] == "my-command"
        assert commands[0]["description"] == "My custom command"
        assert commands[0]["format"] == "md"
