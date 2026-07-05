"""Workspace discovery for skills, extensions, and commands.

Phase 2 responsibilities (plan.md):
- Discover skills, extensions, commands from workspace directories (FR-003)
- Validate duplicate tool names across skills (FR-011)
- Handle empty/missing directories gracefully (Edge Cases)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from minirun.log import get_logger
from minirun.workspace.models import (
    WorkspaceCommand,
    WorkspaceProfile,
    WorkspaceProfileOverride,
    WorkspaceSkill,
)

log = get_logger("workspace.discovery")

# ── FR-011: maximum default timeout for skill handlers ──────────────────

SKILL_EXECUTION_TIMEOUT_DEFAULT = 30  # seconds


class WorkspaceDiscovery:
    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root

    # ── Profiles ───────────────────────────────────────────────────────

    def discover_profiles(self) -> list[WorkspaceProfile]:
        profiles: list[WorkspaceProfile] = []
        profiles_dir = self.root / "profiles"
        if not profiles_dir.is_dir():
            log.debug("Profiles directory does not exist: %s", profiles_dir)
            return profiles

        for entry in sorted(profiles_dir.iterdir()):
            if entry.suffix == ".md":
                try:
                    profile = WorkspaceProfile.from_file(entry)
                    profiles.append(profile)
                    log.debug("Loaded profile: %s", profile.name)
                except Exception as exc:
                    log.warning("Failed to load profile %s: %s", entry, exc)

        return profiles

    def get_profile(self, name: str) -> WorkspaceProfile | None:
        for profile in self.discover_profiles():
            if profile.name == name:
                return profile
        return None

    # ── Skills (FR-003 / Step 2.1) ─────────────────────────────────────

    def discover_skills(self) -> list[WorkspaceSkill]:
        """Discover skills from ``workspace/skills/*.yaml``.

        Validates duplicate tool names across all loaded skills (FR-011).
        The first-loaded definition wins; duplicates are logged as warnings.
        """
        skills: list[WorkspaceSkill] = []
        skills_dir = self.root / "skills"
        if not skills_dir.is_dir():
            log.debug("Skills directory does not exist: %s — skipping", skills_dir)
            return skills

        for entry in sorted(skills_dir.iterdir()):
            if entry.suffix in (".yaml", ".yml"):
                try:
                    skill = WorkspaceSkill.from_file(entry)
                    skills.append(skill)
                    log.debug("Loaded skill: %s", skill.name)
                except Exception as exc:
                    log.warning("Failed to load skill %s: %s", entry, exc)

        # Step 2.2: Validate duplicate tool names across skills (FR-011)
        self._validate_skill_duplicates(skills)

        return skills

    @staticmethod
    def _validate_skill_duplicates(skills: list[WorkspaceSkill]) -> None:
        """Log warnings for duplicate tool names across skills (FR-011).

        The first-loaded tool wins; subsequent duplicates are skipped.
        """
        seen: dict[str, str] = {}  # tool_name → skill_name
        for skill in skills:
            for tool in skill.tools:
                if tool.name in seen:
                    log.warning(
                        "FR-011: duplicate tool '%s' in skill '%s' — "
                        "already defined by skill '%s'; keeping first-loaded",
                        tool.name,
                        skill.name,
                        seen[tool.name],
                    )
                else:
                    seen[tool.name] = skill.name

    def get_skill(self, name: str) -> WorkspaceSkill | None:
        for skill in self.discover_skills():
            if skill.name == name:
                return skill
        return None

    # ── Profile Extensions (Step 2.7) ───────────────────────────────────

    def discover_extensions(self) -> list[WorkspaceProfileOverride]:
        """Discover profile extensions from ``workspace/profiles/extensions/*.yaml``.

        Returns declarative data that extends a base profile with additional
        instructions and allowed_tools (see data-model.md).
        """
        extensions: list[WorkspaceProfileOverride] = []
        extensions_dir = self.root / "profiles" / "extensions"
        if not extensions_dir.is_dir():
            log.debug(
                "Extensions directory does not exist: %s — skipping",
                extensions_dir,
            )
            return extensions

        for entry in sorted(extensions_dir.iterdir()):
            if entry.suffix in (".yaml", ".yml"):
                try:
                    ext = WorkspaceProfileOverride.from_file(entry)
                    extensions.append(ext)
                    log.debug("Loaded profile extension: %s", ext.name)
                except Exception as exc:
                    log.warning("Failed to load profile extension %s: %s", entry, exc)

        return extensions

    def get_extension(self, name: str) -> WorkspaceProfileOverride | None:
        for ext in self.discover_extensions():
            if ext.name == name:
                return ext
        return None

    # ── Profile Overrides (legacy — kept for backward compat) ───────────

    def discover_overrides(self) -> list[WorkspaceProfileOverride]:
        """Discover profile overrides from ``workspace/profiles/*.yaml``.

        .. deprecated::
            Use :meth:`discover_extensions` instead. This method reads from
            ``workspace/profiles/`` root (not ``extensions/`` subdirectory).
        """
        overrides: list[WorkspaceProfileOverride] = []
        overrides_dir = self.root / "profiles"
        if not overrides_dir.is_dir():
            log.debug("Profiles directory does not exist: %s", overrides_dir)
            return overrides

        for entry in sorted(overrides_dir.iterdir()):
            if entry.suffix in (".yaml", ".yml"):
                try:
                    override = WorkspaceProfileOverride.from_file(entry)
                    overrides.append(override)
                    log.debug("Loaded profile override: %s", override.name)
                except Exception as exc:
                    log.warning("Failed to load profile override %s: %s", entry, exc)

        return overrides

    def get_override(self, name: str) -> WorkspaceProfileOverride | None:
        for override in self.discover_overrides():
            if override.name == name:
                return override
        return None

    # ── Commands (Step 2.8) ────────────────────────────────────────────

    def discover_commands(self) -> list[WorkspaceCommand]:
        """Discover commands from ``workspace/commands/*``.

        Non-executable command files are skipped with a warning (Edge Cases).
        Empty or missing directories are handled gracefully (Step 2.9).
        """
        commands: list[WorkspaceCommand] = []
        commands_dir = self.root / "commands"
        if not commands_dir.is_dir():
            log.debug("Commands directory does not exist: %s — skipping", commands_dir)
            return commands

        for entry in sorted(commands_dir.iterdir()):
            if not entry.is_file():
                continue

            # Accept known extensions (.md=metadata, .py/.sh=scripts)
            # or any executable file (Edge Cases)
            if entry.suffix in (".md", ".py", ".sh") or os.access(entry, os.X_OK):
                # Skip non-executable script files (Edge Cases)
                # .md files are metadata/descriptors and don't need +x
                if entry.suffix not in (".md", "") and not os.access(entry, os.X_OK):
                    log.warning(
                        "Command file '%s' is not executable — skipping",
                        entry,
                    )
                    continue
                try:
                    command = WorkspaceCommand.from_file(entry)
                    commands.append(command)
                    log.debug("Discovered command: %s", command.name)
                except Exception as exc:
                    log.warning("Failed to load command %s: %s", entry, exc)

        return commands

    def get_command(self, name: str) -> WorkspaceCommand | None:
        for command in self.discover_commands():
            if command.name == name:
                return command
        return None

    # ── Bulk discovery ──────────────────────────────────────────────────

    def discover_all(self) -> dict[str, list[Any]]:
        return {
            "profiles": self.discover_profiles(),
            "skills": self.discover_skills(),
            "extensions": self.discover_extensions(),
            "overrides": self.discover_overrides(),
            "commands": self.discover_commands(),
        }
