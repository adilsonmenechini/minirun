from __future__ import annotations

import os
from pathlib import Path

from minirun.log import get_logger
from minirun.profiles import discover_profiles as _discover_profiles

log = get_logger("workspace")

SUBDIRS = ["memory", "agents", "commands", "skills"]


class Workspace:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or self._default_root())
        log.debug("Workspace root: %s", self.root)

    @staticmethod
    def _default_root() -> str:
        return os.environ.get("MINIRUN_WORKSPACE", str(Path.cwd() / "workspace"))

    def init(self) -> bool:
        created = False
        for name in SUBDIRS:
            target = self.root / name
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                created = True
                log.info("Created workspace directory: %s", target)
        if not created:
            log.debug("Workspace already initialised at %s", self.root)
        return created

    def discover_profiles(self) -> list[dict[str, str]]:
        return _discover_profiles(self.root / "agents")

    def discover_skills(self) -> list[dict[str, str]]:
        return self._discover_from_dir(self.root / "skills", (".md", ".yaml", ".yml"))

    def discover_commands(self) -> list[dict[str, str]]:
        return self._discover_from_dir(self.root / "commands", (".sh", ".py"))

    @staticmethod
    def _discover_from_dir(
        directory: Path, extensions: tuple[str, ...]
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not directory.is_dir():
            log.debug("Directory does not exist: %s", directory)
            return items
        for entry in sorted(directory.iterdir()):
            if entry.suffix in extensions:
                fmt = entry.suffix.lstrip(".")
                items.append({"name": entry.stem, "format": fmt, "path": str(entry)})
        log.debug("Discovered %d item(s) in %s", len(items), directory)
        return items
