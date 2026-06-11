# Codex危険バイパスenv対応

## タスクの内容
- Raspberry Pi上の非対話運用でCodex CLIの承認待ちやsandbox制約を完全に外せるよう、`.env` から `--dangerously-bypass-approvals-and-sandbox` を指定可能にする。
- `CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=true` の場合、`codex exec` に `--dangerously-bypass-approvals-and-sandbox` を付与する。
- 危険バイパス有効時は `CODEX_SANDBOX` より優先し、両方を同時に渡さない。
- README、`.env.example`、Raspberry Pi systemd手順へ運用上の注意を追記する。

## ステータス
- DONE

## 完了条件
- 未設定時は既存挙動を維持する。
- `CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=true` の場合に `--dangerously-bypass-approvals-and-sandbox` が付与される。
- 危険バイパス有効時に `--sandbox` が同時付与されない。
- `uv run pytest tests/test_codex_runner.py` が通る。
