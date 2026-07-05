from __future__ import annotations

from pathlib import Path

import pytest

from minirun.tools.filesystem import FilesystemTool


@pytest.fixture
def tool() -> FilesystemTool:
    return FilesystemTool()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with test files."""
    (tmp_path / "readme.md").write_text("# Hello\nThis is a test file.\nLine 3\n")
    (tmp_path / "config.yaml").write_text("key: value\nsetting: enabled\n")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "notes.txt").write_text("Subdirectory file\nWith multiple lines\n")
    (tmp_path / "empty.md").write_text("")
    return tmp_path


# ── FilesystemTool base execute ─────────────────────────────────────────


class TestFilesystemToolExecute:
    def test_unknown_operation(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "unknown"})
        assert result["success"] is False
        assert "unknown" in result["error"]


# ── US1: Read ───────────────────────────────────────────────────────────


class TestFilesystemRead:
    def test_read_text_file(self, tool: FilesystemTool, tmp_workspace: Path) -> None:
        path = str(tmp_workspace / "readme.md")
        result = tool.execute({"_operation": "read", "path": path})
        assert result["success"] is True
        assert result["data"] == "# Hello\nThis is a test file.\nLine 3\n"
        assert result["encoding"] == "utf-8"

    def test_read_empty_file(self, tool: FilesystemTool, tmp_workspace: Path) -> None:
        path = str(tmp_workspace / "empty.md")
        result = tool.execute({"_operation": "read", "path": path})
        assert result["success"] is True
        assert result["data"] == ""

    def test_read_nonexistent_file(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "read", "path": "/nonexistent/file.txt"})
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_read_missing_path_param(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "read"})
        assert result["success"] is False
        assert "missing" in result["error"].lower()

    def test_read_directory_returns_error(
        self, tool: FilesystemTool, tmp_workspace: Path
    ) -> None:
        result = tool.execute({"_operation": "read", "path": str(tmp_workspace)})
        assert result["success"] is False
        assert "not a file" in result["error"].lower()

    def test_read_binary_falls_back_to_base64(
        self, tool: FilesystemTool, tmp_path: Path
    ) -> None:
        # Write actual binary bytes that fail text decoding
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a")  # PNG header
        result = tool.execute({"_operation": "read", "path": str(binary_file)})
        assert result["success"] is True
        assert result["encoding"] == "base64"


# ── US2: Write ──────────────────────────────────────────────────────────


class TestFilesystemWrite:
    def test_write_new_file(self, tool: FilesystemTool, tmp_path: Path) -> None:
        path = str(tmp_path / "new_file.txt")
        result = tool.execute(
            {"_operation": "write", "path": path, "content": "hello world"}
        )
        assert result["success"] is True
        assert tmp_path.joinpath("new_file.txt").read_text() == "hello world"

    def test_write_overwrites_existing(
        self, tool: FilesystemTool, tmp_path: Path
    ) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("old content")
        result = tool.execute(
            {
                "_operation": "write",
                "path": str(target),
                "content": "new content",
            }
        )
        assert result["success"] is True
        assert target.read_text() == "new content"

    def test_write_with_create_parents(
        self, tool: FilesystemTool, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "a" / "b" / "c" / "deep.txt")
        result = tool.execute(
            {
                "_operation": "write",
                "path": path,
                "content": "deep file",
                "create_parents": True,
            }
        )
        assert result["success"] is True
        assert tmp_path.joinpath("a", "b", "c", "deep.txt").read_text() == "deep file"

    def test_write_missing_path(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "write", "content": "content"})
        assert result["success"] is False
        assert "missing" in result["error"].lower()

    def test_write_missing_content(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "write", "path": "/tmp/test.txt"})
        assert result["success"] is False
        assert "missing" in result["error"].lower()


# ── US4: Grep ───────────────────────────────────────────────────────────


class TestFilesystemGrep:
    def test_grep_finds_matching_lines(
        self, tool: FilesystemTool, tmp_workspace: Path
    ) -> None:
        result = tool.execute(
            {
                "_operation": "grep",
                "pattern": "test",
                "path": str(tmp_workspace),
            }
        )
        assert result["success"] is True
        assert result["matches"] >= 1
        # Should find "test" in readme.md and config.yaml possibly
        files_found = {m["file"] for m in result["data"]}
        assert any("readme.md" in f for f in files_found)

    def test_grep_no_match(self, tool: FilesystemTool, tmp_workspace: Path) -> None:
        result = tool.execute(
            {
                "_operation": "grep",
                "pattern": "ZZZZNOMATCHZZZZ",
                "path": str(tmp_workspace),
            }
        )
        assert result["success"] is True
        assert result["matches"] == 0

    def test_grep_respects_max_results(
        self, tool: FilesystemTool, tmp_workspace: Path
    ) -> None:
        result = tool.execute(
            {
                "_operation": "grep",
                "pattern": ".",
                "path": str(tmp_workspace),
                "max_results": 2,
            }
        )
        assert result["success"] is True
        assert result["matches"] <= 2

    def test_grep_missing_pattern(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "grep", "path": "/tmp"})
        assert result["success"] is False
        assert "missing" in result["error"].lower()

    def test_grep_invalid_regex(
        self, tool: FilesystemTool, tmp_workspace: Path
    ) -> None:
        result = tool.execute(
            {
                "_operation": "grep",
                "pattern": "[invalid",
                "path": str(tmp_workspace),
            }
        )
        assert result["success"] is False
        assert "regex" in result["error"].lower()


# ── US5: Glob ───────────────────────────────────────────────────────────


class TestFilesystemGlob:
    def test_glob_finds_files(self, tool: FilesystemTool, tmp_workspace: Path) -> None:
        result = tool.execute(
            {
                "_operation": "glob",
                "pattern": "*.md",
                "root": str(tmp_workspace),
            }
        )
        assert result["success"] is True
        assert any(f.endswith("readme.md") for f in result["data"])
        assert any(f.endswith("empty.md") for f in result["data"])

    def test_glob_recursive(self, tool: FilesystemTool, tmp_workspace: Path) -> None:
        result = tool.execute(
            {
                "_operation": "glob",
                "pattern": "**/*",
                "root": str(tmp_workspace),
            }
        )
        assert result["success"] is True
        # Should find files in subdirectories too
        assert any("subdir" in f for f in result["data"])

    def test_glob_no_match(self, tool: FilesystemTool, tmp_workspace: Path) -> None:
        result = tool.execute(
            {
                "_operation": "glob",
                "pattern": "*.nonexistent",
                "root": str(tmp_workspace),
            }
        )
        assert result["success"] is True
        assert result["total"] == 0

    def test_glob_missing_pattern(self, tool: FilesystemTool) -> None:
        result = tool.execute({"_operation": "glob", "root": "."})
        assert result["success"] is False
        assert "missing" in result["error"].lower()

    def test_glob_nonexistent_root(self, tool: FilesystemTool) -> None:
        result = tool.execute(
            {
                "_operation": "glob",
                "pattern": "*.md",
                "root": "/nonexistent_dir_xyz",
            }
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()
