"""Workspace discovery for skills, agents, and commands."""

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


class WorkspaceDiscovery:
    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root

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

    def discover_skills(self) -> list[WorkspaceSkill]:
        skills: list[WorkspaceSkill] = []
        skills_dir = self.root / "skills"
        if not skills_dir.is_dir():
            log.debug("Skills directory does not exist: %s", skills_dir)
            return skills

        for entry in sorted(skills_dir.iterdir()):
            if entry.suffix in (".yaml", ".yml"):
                try:
                    skill = WorkspaceSkill.from_file(entry)
                    skills.append(skill)
                    log.debug("Loaded skill: %s", skill.name)
                except Exception as exc:
                    log.warning("Failed to load skill %s: %s", entry, exc)

        return skills

    def get_skill(self, name: str) -> WorkspaceSkill | None:
        for skill in self.discover_skills():
            if skill.name == name:
                return skill
        return None

    def discover_overrides(self) -> list[WorkspaceProfileOverride]:
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

    def discover_commands(self) -> list[WorkspaceCommand]:
        commands: list[WorkspaceCommand] = []
        commands_dir = self.root / "commands"
        if not commands_dir.is_dir():
            log.debug("Commands directory does not exist: %s", commands_dir)
            return commands

        for entry in sorted(commands_dir.iterdir()):
            if entry.is_file() and (
                entry.suffix in (".md", ".py", ".sh") or os.access(entry, os.X_OK)
            ):
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

    def discover_all(self) -> dict[str, list[Any]]:
        return {
            "profiles": self.discover_profiles(),
            "skills": self.discover_skills(),
            "overrides": self.discover_overrides(),
            "commands": self.discover_commands(),
        }
