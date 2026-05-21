# M7 Claude Code / Codex 両対応

## 目的

- Slack wrapperの実行エンジンをCodex CLI固定からagent engine adapterへ分離する。
- `.env` の `AGENT_ENGINE=codex|claude` でCodex CLI / Claude Codeを切り替えられるようにする。

## 実装方針

- `agent_runner` に共通の `AgentResult` と `run_agent()` を置く。
- Codexは既存の `codex exec --json --output-last-message` を維持する。
- Claude Codeは `claude -p --output-format json` を使い、`result` と `session_id` を読む。
- 会話DBは `agent_engine` / `agent_session_id` を主系にし、既存 `codex_rollout_id` は互換用に残す。
- Slack / Scheduler / schedule intent parser は個別CLIではなく `run_agent()` を呼ぶ。

## 完了条件

- `AGENT_ENGINE=codex` で既存のCodex実行が継続する。
- `AGENT_ENGINE=claude` でClaude Code実行と `--resume` による会話継続ができる。
- 既存SQLiteの `codex_rollout_id` だけを持つ会話が壊れない。
- README、設計書、タスク戦略が両対応に更新されている。
