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
CODEX_SANDBOX=workspace-write
CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=false
CODEX_SKIP_GIT_REPO_CHECK=false
SQLITE_PATH=data/agent.db
SLACK_LOG_CHANNEL=C0123456789
SLACK_FILE_ROOT=share
SLACK_FILE_MAX_BYTES=20971520
SLACK_INBOUND_FILE_ROOT=inbox/slack
SLACK_INBOUND_FILE_MAX_BYTES=20971520
PROACTIVE_ENABLED=false
PROACTIVE_CHANNEL=C0123456789
PROACTIVE_TIMES_PER_DAY=4
PROACTIVE_WINDOW_START=09:00
PROACTIVE_WINDOW_END=22:00
PROACTIVE_MIN_GAP_MINUTES=120
PROACTIVE_TIMEZONE=Asia/Tokyo
```

Codex CLI はデフォルトでプロジェクト直下の `workspace/` を作業ディレクトリとして実行します。
必要に応じて `CODEX_WORKSPACE_DIR` に絶対パス、または起動ディレクトリからの相対パスを指定して変更できます。
`CODEX_SANDBOX=workspace-write` を設定すると、Codexは `CODEX_WORKSPACE_DIR` 配下へ書き込めます。
`CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=true` を設定すると、Codex CLIに `--dangerously-bypass-approvals-and-sandbox` を付与し、`CODEX_SANDBOX` より優先します。信頼済みの外部sandboxや専用Raspberry Pi上での自動実行に限定してください。
runtime workspaceをgit管理しない場合は `CODEX_SKIP_GIT_REPO_CHECK=true` を設定できます。
Slackへworkspaceファイルを送る場合は `SLACK_FILE_ROOT`、Slackから受け取った添付ファイルの保存先は `SLACK_INBOUND_FILE_ROOT` で指定できます。
どちらも未設定時は `CODEX_WORKSPACE_DIR` 配下を使い、ファイルサイズ上限は20MBです。
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

Raspberry Pi上でruntime workspaceへ書き込ませる場合は、`.env` を絶対パスで設定します。

```dotenv
CODEX_CMD=/home/ryopenguin2/.local/bin/codex
CODEX_WORKSPACE_DIR=/home/ryopenguin2/robopen-workspace
CODEX_SANDBOX=workspace-write
CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=false
CODEX_SKIP_GIT_REPO_CHECK=false
```

`robopen-workspace` をgit管理しない場合は `CODEX_SKIP_GIT_REPO_CHECK=true` にしてください。

## Proactive Check-ins

`PROACTIVE_ENABLED=true` にすると、Botがデフォルト機能として1日4回程度、指定チャンネルへ自然な短文で話しかけます。
発話先は `PROACTIVE_CHANNEL` を使い、未設定時は `SLACK_LOG_CHANNEL` にfallbackします。

```dotenv
PROACTIVE_ENABLED=true
PROACTIVE_CHANNEL=C0123456789
PROACTIVE_TIMES_PER_DAY=4
PROACTIVE_WINDOW_START=09:00
PROACTIVE_WINDOW_END=22:00
PROACTIVE_MIN_GAP_MINUTES=120
PROACTIVE_TIMEZONE=Asia/Tokyo
```

時刻は `PROACTIVE_TIMEZONE` 基準で抽選し、SQLiteの `tasks` にone-shotとして保存されます。

## Schedule Commands

Slackから以下の形式でスケジュールを操作できます。cron設定はSQLiteの `tasks` を唯一の正として保存し、Codex workspaceには複製しません。

```text
schedule cron <title> | <m h dom * dow> | <prompt>
schedule once <title> | <ISO8601 UTC> | <prompt>
schedule list
schedule update <task_id> | <m h dom * dow>
schedule delete <task_id>
schedule delete confirm <task_id>
```

月次タスクは日フィールドに `1` から `31` を指定します。たとえば毎月15日09:00 JSTは次のように登録します。

```text
schedule cron 月次リマインド | 0 0 15 * * | 月次の確認事項を知らせて
```

既存cronタスクの時刻変更は自然文でもできます。

```text
#12を毎朝8時に変えて
朝の要約を8時半にして
```

既存タスクの削除は確認を挟み、実行時は物理削除ではなく `cancelled` にします。

```text
#12を削除して
朝の要約を消して
はい
やっぱりやめて
```

## Test

```sh
uv run pytest
```
