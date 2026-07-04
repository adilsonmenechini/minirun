from __future__ import annotations

from pathlib import Path

from minirun.log import get_logger

log = get_logger("profiles")


def discover_profiles(agents_dir: Path) -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    if not agents_dir.is_dir():
        log.debug("Agents directory does not exist: %s", agents_dir)
        return profiles
    for entry in sorted(agents_dir.iterdir()):
        if entry.suffix in (".yaml", ".yml"):
            profiles.append(
                {"name": entry.stem, "format": "yaml", "path": str(entry)}
            )
        elif entry.suffix == ".md":
            profiles.append(
                {"name": entry.stem, "format": "md", "path": str(entry)}
            )
    log.debug("Discovered %d profile(s) in %s", len(profiles), agents_dir)
    return profiles


def load_profile(path: str) -> dict[str, str | None] | None:
    target = Path(path)
    if not target.is_file():
        log.warning("Profile file not found: %s", target)
        return None
    name = target.stem
    return {"name": name, "format": target.suffix.lstrip("."), "path": str(target)}
