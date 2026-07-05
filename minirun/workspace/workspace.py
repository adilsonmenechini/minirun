from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from minirun.log import get_logger
from minirun.profiles import discover_profiles as _discover_profiles
from minirun.profiles import parse_frontmatter

log = get_logger("workspace")

SUBDIRS = ["memory", "profiles", "commands", "skills"]


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
        return _discover_profiles(self.root / "profiles")

    def discover_skills(self) -> list[dict[str, str]]:
        return self._discover_from_dir(
            self.root / "skills", (".md", ".yaml", ".yml"), manifest_name="SKILL"
        )

    def discover_commands(self) -> list[dict[str, str]]:
        return self._discover_from_dir(
            self.root / "commands",
            (".md", ".sh", ".py"),
            manifest_name="COMMAND",
        )

    def save_session(
        self, session_id: str, messages: list[dict[str, Any]], state: dict[str, Any]
    ) -> None:
        path = self.root / "memory" / "sessions" / f"{session_id}.json"
        with open(path, "w") as f:
            json.dump(
                {"session_id": session_id, "messages": messages, "state": state},
                f,
                indent=2,
            )

    def load_session(
        self, session_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        path = self.root / "memory" / "sessions" / f"{session_id}.json"
        if not path.exists():
            log.debug("Session file not found: %s", path)
            return [], {}
        with open(path) as f:
            data = json.load(f)
        return data["messages"], data["state"]

    @staticmethod
    def _discover_from_dir(
        directory: Path,
        extensions: tuple[str, ...],
        manifest_name: str | None = None,
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not directory.is_dir():
            log.debug("Directory does not exist: %s", directory)
            return items
        for entry in sorted(directory.iterdir()):
            if entry.suffix in extensions:
                fmt = entry.suffix.lstrip(".")
                name = entry.stem
                description = ""
                if entry.suffix == ".md":
                    fm = parse_frontmatter(entry)
                    if fm:
                        name = fm.get("name", entry.stem)
                        description = fm.get("description", "")
                items.append(
                    {
                        "name": name,
                        "format": fmt,
                        "path": str(entry),
                        "description": description,
                    }
                )
            elif entry.is_dir() and manifest_name:
                for ext in extensions:
                    manifest = entry / f"{manifest_name}{ext}"
                    if manifest.is_file():
                        fmt = ext.lstrip(".")
                        name = entry.name
                        description = ""
                        if manifest.suffix == ".md":
                            fm = parse_frontmatter(manifest)
                            if fm:
                                name = fm.get("name", entry.name)
                                description = fm.get("description", "")
                        items.append(
                            {
                                "name": name,
                                "format": fmt,
                                "path": str(manifest),
                                "description": description,
                            }
                        )
                        break
        log.debug("Discovered %d item(s) in %s", len(items), directory)
        return items
