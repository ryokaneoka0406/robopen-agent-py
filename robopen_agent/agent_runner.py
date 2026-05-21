from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentResult:
    text: str
    session_id: str | None = None


def get_agent_engine() -> str:
    return os.environ.get("AGENT_ENGINE", "codex").strip().lower() or "codex"


def run_agent(prompt: str, session_id: str | None = None) -> AgentResult:
    engine = get_agent_engine()
    if engine == "codex":
        return run_codex_agent(prompt, session_id)
    if engine == "claude":
        return run_claude_agent(prompt, session_id)
    raise RuntimeError(f"Unsupported AGENT_ENGINE: {engine}")


def run_codex_agent(prompt: str, session_id: str | None = None) -> AgentResult:
    """Run Codex CLI for a single turn and return the final assistant message."""
    codex_cmd = os.environ.get("CODEX_CMD", "codex")
    tmp_dir = Path(tempfile.mkdtemp(prefix="codex-"))
    out_file = tmp_dir / "last.txt"

    args = [codex_cmd, "exec"]
    if session_id:
        args.extend(["resume", session_id])
    args.extend(["--json", "--output-last-message", str(out_file), "-"])

    try:
        completed = subprocess.run(
            args,
            input=prompt,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Codex CLI exited with code {completed.returncode}: {completed.stderr.strip()}"
            )

        extracted_session_id = session_id
        for line in completed.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                extracted_session_id = thread_id

        try:
            text = out_file.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""

        return AgentResult(text=text or "(empty response)", session_id=extracted_session_id)
    except OSError as exc:
        raise RuntimeError(f"Failed to start Codex CLI: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_claude_agent(prompt: str, session_id: str | None = None) -> AgentResult:
    """Run Claude Code in print mode and return the final assistant message."""
    claude_cmd = os.environ.get("CLAUDE_CMD", "claude")
    permission_mode = os.environ.get("CLAUDE_PERMISSION_MODE", "dontAsk").strip() or "dontAsk"
    args = [
        claude_cmd,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        permission_mode,
    ]
    if session_id:
        args.extend(["--resume", session_id])

    allowed_tools = _comma_list_env("CLAUDE_ALLOWED_TOOLS")
    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

    disallowed_tools = _comma_list_env("CLAUDE_DISALLOWED_TOOLS")
    if disallowed_tools:
        args.extend(["--disallowedTools", ",".join(disallowed_tools)])

    try:
        completed = subprocess.run(
            args,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Claude Code exited with code {completed.returncode}: {completed.stderr.strip()}"
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Claude Code returned invalid JSON") from exc

        text = payload.get("result")
        extracted_session_id = payload.get("session_id")
        return AgentResult(
            text=text.strip() if isinstance(text, str) and text.strip() else "(empty response)",
            session_id=extracted_session_id if isinstance(extracted_session_id, str) else session_id,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to start Claude Code: {exc}") from exc


def _comma_list_env(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]
