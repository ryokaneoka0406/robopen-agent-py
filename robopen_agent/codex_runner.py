from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodexResult:
    text: str
    session_id: str | None = None


def run_codex(prompt: str, session_id: str | None = None) -> CodexResult:
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

        return CodexResult(text=text or "(empty response)", session_id=extracted_session_id)
    except OSError as exc:
        raise RuntimeError(f"Failed to start Codex CLI: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

