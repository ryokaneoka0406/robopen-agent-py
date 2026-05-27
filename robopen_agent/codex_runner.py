from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CODEX_WORKSPACE_DIR = PROJECT_ROOT / "workspace"
ALLOWED_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}


@dataclass(frozen=True)
class CodexResult:
    text: str
    session_id: str | None = None


def get_codex_workspace_dir() -> Path:
    """Return the directory where Codex CLI should execute user tasks."""
    configured = os.environ.get("CODEX_WORKSPACE_DIR")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (PROJECT_ROOT / configured_path).resolve()
    return DEFAULT_CODEX_WORKSPACE_DIR


def run_codex(prompt: str, session_id: str | None = None) -> CodexResult:
    """Run Codex CLI for a single turn and return the final assistant message."""
    codex_cmd = os.environ.get("CODEX_CMD", "codex")
    workspace_dir = get_codex_workspace_dir()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    sandbox = _get_codex_sandbox()
    skip_git_repo_check = _get_skip_git_repo_check()
    tmp_dir = Path(tempfile.mkdtemp(prefix="codex-"))
    out_file = tmp_dir / "last.txt"

    args = [codex_cmd, "exec"]
    if sandbox:
        args.extend(["--sandbox", sandbox])
    if skip_git_repo_check:
        args.append("--skip-git-repo-check")
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
            cwd=workspace_dir,
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

        return CodexResult(text=text or "(empty response)", session_id=extracted_session_id)
    except OSError as exc:
        raise RuntimeError(f"Failed to start Codex CLI: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _get_codex_sandbox() -> str | None:
    sandbox = os.environ.get("CODEX_SANDBOX")
    if not sandbox:
        return None
    sandbox = sandbox.strip()
    if not sandbox:
        return None
    if sandbox not in ALLOWED_SANDBOXES:
        allowed = ", ".join(sorted(ALLOWED_SANDBOXES))
        raise ValueError(f"Invalid CODEX_SANDBOX: {sandbox}. Allowed values: {allowed}")
    return sandbox


def _get_skip_git_repo_check() -> bool:
    value = os.environ.get("CODEX_SKIP_GIT_REPO_CHECK")
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
