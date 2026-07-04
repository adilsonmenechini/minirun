from pathlib import Path
from unittest.mock import patch

from minirun.config import find_dotenv, load_env


class TestConfig:
    def test_find_dotenv_not_found(self):
        with patch("pathlib.Path.is_file", return_value=False):
            result = find_dotenv()
            assert result is None

    def test_find_dotenv_found_in_cwd(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST=1")
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = find_dotenv()
            assert result is not None
            assert result.name == ".env"

    def test_load_env_with_explicit_path(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("CUSTOM_URL=http://test.local")
        load_env(str(env_file))
        import os

        assert os.environ.get("CUSTOM_URL") == "http://test.local"

    def test_load_env_nonexistent_path(self):
        load_env("/nonexistent/.env")
        # Should not raise
