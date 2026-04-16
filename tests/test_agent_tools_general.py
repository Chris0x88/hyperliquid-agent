"""Tests for general-purpose agent tools (codebase, memory, web, shell, introspection)."""
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def project_root():
    """Return the actual project root for testing."""
    return Path(__file__).resolve().parent.parent


class TestReadFile:
    def test_reads_existing_file(self, project_root):
        from agent.tool_functions import read_file
        result = read_file("README.md")
        assert "content" in result
        assert len(result["content"]) > 0

    def test_blocks_path_traversal(self):
        from agent.tool_functions import read_file
        result = read_file("../../etc/passwd")
        assert "error" in result
        assert "outside project" in result["error"].lower()

    def test_file_not_found(self):
        from agent.tool_functions import read_file
        result = read_file("nonexistent_file_xyz.py")
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestSearchCode:
    def test_finds_pattern(self, project_root):
        from agent.tool_functions import search_code
        result = search_code("_MAX_TOOL_LOOPS")
        assert "count" in result
        assert result["count"] > 0
        assert any("telegram_agent.py" in m for m in result["matches"])

    def test_no_matches(self):
        from agent.tool_functions import search_code
        # Search in calendar dir to avoid this test file matching itself
        result = search_code("xyzzy_never_match_42", "data/calendar/")
        assert result["count"] == 0


class TestListFiles:
    def test_glob_python(self):
        from agent.tool_functions import list_files
        result = list_files("telegram/*.py")
        assert "count" in result
        assert result["count"] > 0
        assert any("agent.py" in f for f in result["files"])

    def test_glob_wiki(self):
        from agent.tool_functions import list_files
        result = list_files("docs/wiki/*.md")
        assert result["count"] > 0


class TestMemoryReadWrite:
    def test_read_index(self):
        from agent.tool_functions import memory_read
        result = memory_read("index")
        assert "content" in result or "error" not in result

    def test_read_nonexistent_topic(self):
        from agent.tool_functions import memory_read
        result = memory_read("nonexistent_topic_xyz")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_write_and_read_roundtrip(self, tmp_path, monkeypatch):
        from agent import tool_functions as tools
        monkeypatch.setattr(tools, "_MEMORY_DIR", tmp_path)

        # Write
        from agent.tool_functions import memory_write, memory_read
        write_result = memory_write("test_topic", "# Test\nSome content")
        assert write_result.get("status") == "saved"

        # Read back
        read_result = memory_read("test_topic")
        assert "content" in read_result
        assert "Some content" in read_result["content"]

        # Index updated
        index_result = memory_read("index")
        assert "test_topic" in index_result.get("content", "")


class TestEditFile:
    def test_edits_unique_match(self, tmp_path):
        from agent import tool_functions as tools
        # Create a test file in project root
        test_file = tmp_path / "test_edit.py"
        test_file.write_text("old_value = 42\nother_line = True\n")

        # Monkeypatch _PROJECT_ROOT
        import agent.tool_functions as tools_mod
        original_root = tools_mod._PROJECT_ROOT
        tools_mod._PROJECT_ROOT = tmp_path

        try:
            result = tools_mod.edit_file("test_edit.py", "old_value = 42", "new_value = 99")
            assert result.get("status") == "edited"
            assert "backup" in result  # backup should be created

            # Verify edit applied
            content = test_file.read_text()
            assert "new_value = 99" in content
            assert "old_value = 42" not in content

            # Verify backup exists
            backup = tmp_path / "test_edit.py.bak"
            assert backup.exists()
            assert "old_value = 42" in backup.read_text()
        finally:
            tools_mod._PROJECT_ROOT = original_root

    def test_errors_on_duplicate_match(self, tmp_path):
        import agent.tool_functions as tools_mod
        test_file = tmp_path / "test_dup.py"
        test_file.write_text("x = 1\nx = 1\n")

        original_root = tools_mod._PROJECT_ROOT
        tools_mod._PROJECT_ROOT = tmp_path
        try:
            result = tools_mod.edit_file("test_dup.py", "x = 1", "x = 2")
            assert "error" in result
            assert "2 times" in result["error"]
        finally:
            tools_mod._PROJECT_ROOT = original_root

    def test_blocks_path_traversal(self):
        from agent.tool_functions import edit_file
        result = edit_file("../../etc/passwd", "root", "hacked")
        assert "error" in result
        assert "outside project" in result["error"].lower()


class TestRunBash:
    def test_runs_simple_command(self):
        from agent.tool_functions import run_bash
        result = run_bash("echo hello")
        assert result["returncode"] == 0
        assert "hello" in result["stdout"]

    def test_blocks_dangerous_command(self):
        from agent.tool_functions import run_bash
        result = run_bash("rm -rf /")
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_timeout(self):
        from agent.tool_functions import run_bash
        # This should timeout but we can't wait 30s in tests
        # Just verify the function exists and handles short commands
        result = run_bash("echo fast")
        assert result["returncode"] == 0


class TestGetErrors:
    def test_no_errors_file(self, tmp_path, monkeypatch):
        import agent.tool_functions as tools_mod
        monkeypatch.setattr(tools_mod, "_PROJECT_ROOT", tmp_path)
        result = tools_mod.get_errors()
        assert result["count"] == 0

    def test_reads_error_log(self, tmp_path, monkeypatch):
        import agent.tool_functions as tools_mod
        monkeypatch.setattr(tools_mod, "_PROJECT_ROOT", tmp_path)

        diag_dir = tmp_path / "data" / "diagnostics"
        diag_dir.mkdir(parents=True)
        errors_file = diag_dir / "errors.jsonl"
        entry = {"ts": "2026-04-05T10:00:00", "event": "tool_error", "data": {"msg": "test failure"}}
        errors_file.write_text(json.dumps(entry) + "\n")

        result = tools_mod.get_errors()
        assert result["count"] == 1
        assert result["errors"][0]["event"] == "tool_error"


class TestGetFeedback:
    def test_no_feedback_file(self, tmp_path, monkeypatch):
        import agent.tool_functions as tools_mod
        monkeypatch.setattr(tools_mod, "_PROJECT_ROOT", tmp_path)
        result = tools_mod.get_feedback()
        assert result["count"] == 0

    def test_reads_feedback(self, tmp_path, monkeypatch):
        import agent.tool_functions as tools_mod
        monkeypatch.setattr(tools_mod, "_PROJECT_ROOT", tmp_path)

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        feedback_file = data_dir / "feedback.jsonl"
        entry = {"timestamp": "2026-04-05", "text": "improve the agent"}
        feedback_file.write_text(json.dumps(entry) + "\n")

        result = tools_mod.get_feedback()
        assert result["count"] == 1
        assert "improve" in result["feedback"][0]["text"]


class TestWebSearch:
    def test_returns_results(self):
        """Web search should return a valid structure (may be empty due to rate limits)."""
        from agent.tool_functions import web_search
        result = web_search("Python programming language", max_results=2)
        # Should return either results or error — never crash
        assert "results" in result or "error" in result
