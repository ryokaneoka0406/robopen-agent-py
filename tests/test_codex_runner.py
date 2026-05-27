import json
import os
from pathlib import Path

from robopen_agent import codex_runner


class CompletedProcessStub:
    returncode = 0
    stderr = ""
    stdout = json.dumps({"thread_id": "thread-123"})


def test_run_codex_uses_default_workspace(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["cwd"] = kwargs["cwd"]
        out_file = Path(args[0][args[0].index("--output-last-message") + 1])
        out_file.write_text("ok", encoding="utf-8")
        return CompletedProcessStub()

    monkeypatch.delenv("CODEX_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    result = codex_runner.run_codex("hello")

    assert result.text == "ok"
    assert result.session_id == "thread-123"
    assert captured["cwd"] == codex_runner.DEFAULT_CODEX_WORKSPACE_DIR
    assert codex_runner.DEFAULT_CODEX_WORKSPACE_DIR.is_dir()


def test_run_codex_allows_workspace_override(tmp_path, monkeypatch):
    captured = {}
    override = tmp_path / "custom-workspace"

    def fake_run(*args, **kwargs):
        captured["cwd"] = kwargs["cwd"]
        out_file = Path(args[0][args[0].index("--output-last-message") + 1])
        out_file.write_text("ok", encoding="utf-8")
        return CompletedProcessStub()

    monkeypatch.setenv("CODEX_WORKSPACE_DIR", os.fspath(override))
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    codex_runner.run_codex("hello")

    assert captured["cwd"] == override.resolve()
    assert override.is_dir()


def test_relative_workspace_override_is_project_root_relative(monkeypatch):
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", "custom-workspace")

    assert codex_runner.get_codex_workspace_dir() == (
        codex_runner.PROJECT_ROOT / "custom-workspace"
    ).resolve()


def test_run_codex_adds_sandbox_option(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args[0]
        out_file = Path(args[0][args[0].index("--output-last-message") + 1])
        out_file.write_text("ok", encoding="utf-8")
        return CompletedProcessStub()

    monkeypatch.setenv("CODEX_SANDBOX", "workspace-write")
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    codex_runner.run_codex("hello")

    assert captured["args"][0:4] == ["codex", "exec", "--sandbox", "workspace-write"]


def test_run_codex_adds_skip_git_repo_check(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args[0]
        out_file = Path(args[0][args[0].index("--output-last-message") + 1])
        out_file.write_text("ok", encoding="utf-8")
        return CompletedProcessStub()

    monkeypatch.setenv("CODEX_SKIP_GIT_REPO_CHECK", "true")
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    codex_runner.run_codex("hello")

    assert "--skip-git-repo-check" in captured["args"]


def test_run_codex_keeps_codex_cmd_as_binary_path(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args[0]
        out_file = Path(args[0][args[0].index("--output-last-message") + 1])
        out_file.write_text("ok", encoding="utf-8")
        return CompletedProcessStub()

    monkeypatch.setenv("CODEX_CMD", "/home/ryopenguin2/.local/bin/codex")
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_run)

    codex_runner.run_codex("hello")

    assert captured["args"][0] == "/home/ryopenguin2/.local/bin/codex"


def test_run_codex_rejects_invalid_sandbox(monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX", "invalid")

    try:
        codex_runner.run_codex("hello")
    except ValueError as exc:
        assert "Invalid CODEX_SANDBOX" in str(exc)
    else:
        raise AssertionError("Expected invalid CODEX_SANDBOX to raise ValueError")
