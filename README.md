# robopen-agent-py

Slack から Codex CLI / Claude Code を呼び出す個人用エージェントの Python 実装です。

## Setup

```sh
uv sync
cp .env.example .env
```

`.env` に Slack token を設定します。

```dotenv
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
AGENT_ENGINE=codex
CODEX_CMD=codex
CLAUDE_CMD=claude
CLAUDE_PERMISSION_MODE=dontAsk
SQLITE_PATH=data/agent.db
SLACK_LOG_CHANNEL=C0123456789
```

`AGENT_ENGINE=claude` にすると Claude Code の headless/print mode を使います。Claude Code 側は事前にログインまたはAPI key設定を済ませてください。

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
