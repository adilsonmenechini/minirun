from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

from minirun.log import get_logger

log = get_logger("profiles")


def parse_frontmatter(path: Path) -> dict[str, str] | None:
    """Parse YAML frontmatter (--- delimited) from a markdown file.

    Returns a dict of frontmatter fields, or None if no frontmatter is found.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        log.debug("Cannot read %s for frontmatter: %s", path, exc)
        return None

    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        log.debug("Invalid frontmatter YAML in %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        return None
    return cast(dict[str, str], data)


def _validate_yaml(path: Path) -> bool:
    """Validate a YAML file. Returns True if valid, False if invalid."""
    try:
        with path.open("r", encoding="utf-8") as f:
            yaml.safe_load(f)
        return True
    except yaml.YAMLError as e:
        log.warning("Skipping invalid YAML profile %s: %s", path, e)
        return False


def discover_profiles(agents_dir: Path) -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    if not agents_dir.is_dir():
        log.debug("Agents directory does not exist: %s", agents_dir)
        return profiles
    for entry in sorted(agents_dir.iterdir()):
        if entry.suffix in (".yaml", ".yml"):
            if not _validate_yaml(entry):
                continue
            profiles.append(
                {
                    "name": entry.stem,
                    "format": "yaml",
                    "path": str(entry),
                    "description": "",
                }
            )
        elif entry.suffix == ".md":
            fm = parse_frontmatter(entry)
            name = fm.get("name", entry.stem) if fm else entry.stem
            desc = fm.get("description", "") if fm else ""
            profiles.append(
                {
                    "name": name,
                    "format": "md",
                    "path": str(entry),
                    "description": desc,
                }
            )
        elif entry.is_dir():
            profile_exts = (".yaml", ".yml", ".md")
            for ext in profile_exts:
                manifest = entry / f"PROFILE{ext}"
                if manifest.is_file():
                    fmt = ext.lstrip(".")
                    if ext in (".yaml", ".yml") and not _validate_yaml(manifest):
                        continue
                    name = entry.name
                    desc = ""
                    if ext == ".md":
                        fm = parse_frontmatter(manifest)
                        if fm:
                            name = fm.get("name", entry.name)
                            desc = fm.get("description", "")
                    profiles.append(
                        {
                            "name": name,
                            "format": fmt,
                            "path": str(manifest),
                            "description": desc,
                        }
                    )
                    break
    log.debug("Discovered %d profile(s) in %s", len(profiles), agents_dir)
    return profiles


def load_profile(path: str) -> dict[str, str | None] | None:
    target = Path(path)
    if not target.is_file():
        log.warning("Profile file not found: %s", target)
        return None
    name = target.stem
    description = ""
    if target.suffix == ".md":
        fm = parse_frontmatter(target)
        if fm:
            name = fm.get("name", target.stem)
            description = fm.get("description", "")
    return {
        "name": name,
        "format": target.suffix.lstrip("."),
        "path": str(target),
        "description": description,
    }


def list_profiles(
    builtin_agents_dir: Path | None = None,
    workspace_agents_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Combine profiles from built-in and workspace directories.

    Workspace profiles take precedence over built-in profiles with the same name.
    """
    all_profiles: dict[str, dict[str, str]] = {}

    if builtin_agents_dir and builtin_agents_dir.is_dir():
        for profile in discover_profiles(builtin_agents_dir):
            all_profiles[profile["name"]] = profile

    if workspace_agents_dir and workspace_agents_dir.is_dir():
        for profile in discover_profiles(workspace_agents_dir):
            all_profiles[profile["name"]] = profile

    return list(all_profiles.values())
