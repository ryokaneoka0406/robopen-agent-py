# M1 永続化: SQLiteメモリ実装

## タイトル
M1 永続化: SQLiteメモリ実装

## タスクの内容
- conversations / messages / tasks の初期スキーマを定義する。
- SlackスレッドIDとcodex_rollout_idの対応を保存・復元できるようにする。
- 過去メッセージと要約を再注入し、スレッド継続文脈を維持する。

## ステータス
- DONE

## 実装内容（詳細）
- `robopen_agent/memory_store.py` を新規作成し、SQLite DB初期化と以下3テーブルの自動作成を追加。
  - `conversations`
  - `messages`
  - `tasks`
- `MemoryStore.get_or_create_conversation` を追加し、Slackの `thread_ts`（または投稿 `ts`）単位で会話メタを作成・再利用するようにした。
- `MemoryStore.append_message` で user/assistant の発話を `messages` に保存し、`conversations.last_active_at` を更新するようにした。
- `MemoryStore.get_recent_context` / `get_summary` を追加し、直近メッセージと要約（summary）を参照できるようにした。
- `robopen_agent/app.py` を更新し、Slackイベント処理時に以下を行うようにした。
  1. スレッド単位で conversation を取得/作成
  2. ユーザー入力を messages へ保存
  3. 保存済みの `codex_rollout_id` があれば `codex exec resume` で同じCodex文脈を再利用する
  4. 応答を messages へ保存
- Python標準ライブラリの `sqlite3` を使用するため、追加のDBドライバ依存は不要。

## ローカルでの動作確認方法
1. 依存関係をインストール
   - `uv sync`
2. テスト
   - `uv run pytest`
3. Slack Socket Mode 実行
   - 例: `SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... CODEX_CMD=codex SQLITE_PATH=data/agent.db uv run robopen-agent`
4. SlackでBotにDMまたはメンションして会話
   - 同一スレッドで複数回発話すると、前回までのメッセージがコンテキストとして再注入される。
5. DB確認（任意）
   - `sqlite3 data/agent.db '.tables'`
   - `sqlite3 data/agent.db 'select id, slack_thread_ts, last_active_at from conversations order by id desc limit 5;'`
   - `sqlite3 data/agent.db 'select conversation_id, role, substr(content,1,60), created_at from messages order by id desc limit 10;'`

## 補足
- `codex_rollout_id` はスキーマに含めているが、実際の `codex resume` 連携は次タスクで段階的に拡張する。
- 2026-05-27更新: SQLiteはSlackの作業ログとWrapper復元用メタデータに限定する方針へ変更した。`preferences` と `audit_logs` は廃止し、エージェントの人格・長期記憶・スキルは `workspace/` に集約する。
