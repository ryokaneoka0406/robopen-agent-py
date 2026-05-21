import json
import subprocess

import pytest

from robopen_agent.agent_runner import run_agent, run_claude_agent, run_codex_agent


def test_codex_agent_keeps_existing_args(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        out_file = args[args.index("--output-last-message") + 1]
        with open(out_file, "w", encoding="utf-8") as handle:
            handle.write("hello from codex\n")
        return subprocess.CompletedProcess(args, 0, stdout='{"thread_id":"thread-1"}\n', stderr="")

    monkeypatch.setenv("CODEX_CMD", "codex-test")
    monkeypatch.setattr("robopen_agent.agent_runner.subprocess.run", fake_run)

    result = run_codex_agent("hello", "old-thread")

    args, kwargs = calls[0]
    assert args[:4] == ["codex-test", "exec", "resume", "old-thread"]
    assert args[-3:] == ["--output-last-message", args[-2], "-"]
    assert kwargs["input"] == "hello"
    assert result.text == "hello from codex"
    assert result.session_id == "thread-1"


def test_claude_agent_builds_print_mode_args(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        payload = {"result": "hello from claude", "session_id": "session-1"}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setenv("CLAUDE_CMD", "claude-test")
    monkeypatch.setenv("CLAUDE_PERMISSION_MODE", "dontAsk")
    monkeypatch.setenv("CLAUDE_ALLOWED_TOOLS", "Read, Edit")
    monkeypatch.setenv("CLAUDE_DISALLOWED_TOOLS", "Bash(rm *)")
    monkeypatch.setattr("robopen_agent.agent_runner.subprocess.run", fake_run)

    result = run_claude_agent("hello", "session-0")

    args, kwargs = calls[0]
    assert args == [
        "claude-test",
        "-p",
        "hello",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--resume",
        "session-0",
        "--allowedTools",
        "Read,Edit",
        "--disallowedTools",
        "Bash(rm *)",
    ]
    assert "input" not in kwargs
    assert result.text == "hello from claude"
    assert result.session_id == "session-1"


def test_run_agent_rejects_unknown_engine(monkeypatch):
    monkeypatch.setenv("AGENT_ENGINE", "unknown")

    with pytest.raises(RuntimeError, match="Unsupported AGENT_ENGINE"):
        run_agent("hello")
