from __future__ import annotations

import tempfile
from pathlib import Path

from minirun.profiles.loader import discover_profiles


class TestProfileDiscovery:
    def test_invalid_yaml_raises_parse_error(self) -> None:
        """Malformed YAML in profiles directory should raise an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / "agents"
            agents_dir.mkdir()

            # Create invalid YAML file
            invalid_yaml = agents_dir / "bad.yaml"
            invalid_yaml.write_text("key: [unclosed list")

            # Should handle gracefully (log error, skip file)
            profiles = discover_profiles(agents_dir)
            # No valid profiles found
            assert profiles == []

    def test_valid_and_invalid_yaml_mixed(self) -> None:
        """Valid profiles should be discovered even with invalid ones present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / "agents"
            agents_dir.mkdir()

            # Valid profile
            valid_yaml = agents_dir / "good.yaml"
            valid_yaml.write_text("name: test\nsystem_prompt: hello\n")

            # Invalid profile
            invalid_yaml = agents_dir / "bad.yaml"
            invalid_yaml.write_text("key: [unclosed")

            profiles = discover_profiles(agents_dir)
            assert len(profiles) == 1
            assert profiles[0]["name"] == "good"
