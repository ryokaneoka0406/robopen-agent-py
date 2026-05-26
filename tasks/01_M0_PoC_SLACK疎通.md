# M0 PoC: Slack DM 疎通

## タスクの内容
- Slack Socket ModeでDM/メンションを受信し、Wrapper経由でCodex CLIへ入力を渡す。
- Codex CLIの応答をSlackへ返す最小フローを構築する。
- ローカル環境で1往復の対話が成立することを確認する。

## ステータス
- DONE

## 実装内容（詳細）

### 1. 実装ファイル
- `robopen_agent/app.py`
  - Slack Bolt for Python (Socket Mode) を起動。
  - DMまたはメンションを受信したときだけ処理。
  - 受信テキストをCodex実行へ渡し、返答をSlackへ返信。
- `robopen_agent/codex_runner.py`
  - `codex exec --json --output-last-message <file> -` をサブプロセス実行。
  - Codex CLIの実行ディレクトリはデフォルトでプロジェクト直下の `workspace/` とし、`CODEX_WORKSPACE_DIR` で上書き可能にする。
  - 最終応答ファイルを返却し、異常終了時はstderrを含めて例外化。
- `pyproject.toml`
  - `uv run robopen-agent` で起動できるコンソールスクリプトを定義。
  - 依存として `slack-bolt` / `python-dotenv` を追加。
- `.env.example`
  - `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` / `CODEX_CMD` の設定例を追加。

### 2. 最小フロー（M0スコープ）
1. Slack Socket ModeでDM/メンションイベントを受信。
2. Wrapper層（`robopen_agent/app.py`）で入力文を抽出。
3. `robopen_agent/codex_runner.py` がCodex CLIを実行。
4. 実行結果をSlackへ返信。

### 3. エラーハンドリング
- 必須環境変数が不足している場合、起動時に即時エラーで停止。
- Codex CLIの実行失敗時、Slackへエラー内容を通知。
- 空メッセージは実行せず、入力要求を返信。

### 4. 設計整合性
- `documents/designdoc.md` のM0完了条件（Slack DMからCodex CLIを叩いて返す1往復）を満たす最小構成として実装。
- `tasks/strategy.md` の依存順序（01→02）に沿って、永続化前の疎通検証を先行。

### 5. 次タスクへの引き継ぎ（M1）
- `slack_thread_ts` をキーに会話コンテキストを保存/復元する `memory_store` を接続する。
- 現在の単発実行フローを `session_manager` 経由に拡張し、スレッド継続時は同一文脈を再利用する。
