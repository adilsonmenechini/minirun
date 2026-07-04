from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from minirun.log import get_logger

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

log = get_logger("config")

SETTINGS_PATH = Path(__file__).parent / "settings.yaml"

_DEFAULTS: dict[str, Any] = {
    "log_level": "INFO",
    "provider": {
        "openai": {
            "model": "gpt-4o",
            "max_tokens": None,
        },
        "anthropic": {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
        },
    },
}


def _deep_get(d: Any, keys: tuple[str, ...]) -> Any | None:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def load_yaml(path: Path | None = None) -> dict[str, Any]:
    if yaml is None:
        log.warning("PyYAML not installed, skipping settings.yaml")
        return {}

    target = path or SETTINGS_PATH
    if not target.is_file():
        log.debug("Settings file not found: %s", target)
        return {}

    try:
        with open(target) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            log.warning("Settings file %s is empty or invalid, ignoring", target)
            return {}
        log.info("Loaded settings from %s", target)
        return data
    except (yaml.YAMLError, OSError) as exc:
        log.warning("Failed to load settings from %s: %s", target, exc)
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_settings(path: Path | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = deepcopy(_DEFAULTS)

    yaml_data = load_yaml(path)
    _deep_merge(merged, yaml_data)

    return merged


def get_setting(
    key_path: str,
    settings: dict[str, Any] | None = None,
    default: Any = None,
) -> Any | None:
    resolved = settings if settings is not None else load_settings()
    keys = key_path.split(".")
    return _deep_get(resolved, tuple(keys)) or default
