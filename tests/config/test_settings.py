from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from minirun.config.loader import get_setting, load_settings, load_yaml


class TestLoadYaml:
    def test_load_yaml_valid_file(self, tmp_path: Path) -> None:
        yml = tmp_path / "settings.yaml"
        yml.write_text("provider:\n  openai:\n    model: gpt-4o-mini\n")
        data = load_yaml(yml)
        assert data["provider"]["openai"]["model"] == "gpt-4o-mini"

    def test_load_yaml_missing_file(self, tmp_path: Path) -> None:
        data = load_yaml(tmp_path / "nonexistent.yaml")
        assert data == {}

    def test_load_yaml_invalid_yaml(self, tmp_path: Path) -> None:
        yml = tmp_path / "bad.yaml"
        yml.write_text(": invalid yaml [[[")
        data = load_yaml(yml)
        assert data == {}

    def test_load_yaml_empty_file(self, tmp_path: Path) -> None:
        yml = tmp_path / "empty.yaml"
        yml.write_text("")
        data = load_yaml(yml)
        assert data == {}


class TestDefaults:
    def test_defaults_used_when_no_yaml(self) -> None:
        with patch("minirun.config.loader.load_yaml", return_value={}):
            settings = load_settings()
        assert settings["provider"]["openai"]["model"] == "gpt-4o"
        assert settings["provider"]["anthropic"]["max_tokens"] == 4096

    def test_yaml_overrides_defaults(self) -> None:
        yaml_data = {"provider": {"openai": {"model": "gpt-4o-turbo"}}}
        with patch("minirun.config.loader.load_yaml", return_value=yaml_data):
            settings = load_settings()
        assert settings["provider"]["openai"]["model"] == "gpt-4o-turbo"

    def test_get_setting_nested(self) -> None:
        settings = {"provider": {"openai": {"model": "gpt-4o"}}}
        result = get_setting("provider.openai.model", settings)
        assert result == "gpt-4o"

    def test_get_setting_missing_default(self) -> None:
        result = get_setting("provider.nonexistent", {})
        assert result is None
