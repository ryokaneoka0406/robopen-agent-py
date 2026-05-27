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
`.env` にはSlack tokenなどのsecretを含むため、リポジトリへコミットしないでください。

## Run

```sh
uv run robopen-agent
```

または:

```sh
uv run python -m robopen_agent
```

## Raspberry Pi 常駐

本番運用ではRaspberry Pi上で `uv run robopen-agent` をsystemd serviceとして起動します。
SSHを切っても動き続け、Raspberry Pi再起動後も自動起動できます。

手順は [documents/raspberry-pi-systemd.md](documents/raspberry-pi-systemd.md) を参照してください。
短時間の検証には `tmux` も使えますが、常時起動の標準はsystemdです。

## Test

```sh
uv run pytest
```
