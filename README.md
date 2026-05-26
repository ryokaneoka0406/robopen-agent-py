# robopen-agent-py

Slack から Codex CLI を呼び出す個人用エージェントの Python 実装です。

## Setup

```sh
uv sync
cp .env.example .env
```

`.env` に Slack token を設定します。

```dotenv
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
CODEX_CMD=codex
CODEX_WORKSPACE_DIR=workspace
SQLITE_PATH=data/agent.db
SLACK_LOG_CHANNEL=C0123456789
```

Codex CLI はデフォルトでプロジェクト直下の `workspace/` を作業ディレクトリとして実行します。
必要に応じて `CODEX_WORKSPACE_DIR` に絶対パス、または起動ディレクトリからの相対パスを指定して変更できます。

## Run

```sh
uv run robopen-agent
```

または:

```sh
uv run python -m robopen_agent
```

## Test

```sh
uv run pytest
```
