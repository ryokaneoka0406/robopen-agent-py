from __future__ import annotations

from .agent_runner import AgentResult as CodexResult
from .agent_runner import run_codex_agent


def run_codex(prompt: str, session_id: str | None = None) -> CodexResult:
    return run_codex_agent(prompt, session_id)
