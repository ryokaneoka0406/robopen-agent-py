# Codex workspace write対応

## タスクの内容
- Raspberry Pi上の `CODEX_WORKSPACE_DIR` にCodexが書き込めるよう、Codex CLIのsandboxを `.env` から指定可能にする。
- `CODEX_SANDBOX=workspace-write` の場合、`codex exec --sandbox workspace-write` を付与する。
- runtime workspaceをgit管理しない場合に備え、`CODEX_SKIP_GIT_REPO_CHECK=true` で `--skip-git-repo-check` を付与する。
- Linuxファイル権限の確認手順をRaspberry Pi運用ドキュメントへ追記する。

## ステータス
- DONE

## 完了条件
- `CODEX_SANDBOX` 未設定時は既存挙動を維持する。
- 許可するsandbox値は `read-only` / `workspace-write` / `danger-full-access` に限定する。
- `CODEX_CMD` は引き続き実行ファイルパスとして扱い、追加引数は専用envから組み立てる。
- `uv run pytest` が通る。
