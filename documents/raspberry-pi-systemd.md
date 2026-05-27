# Raspberry Pi systemd 常駐手順

Raspberry Pi上でSlack疎通機能を常時起動する本番運用手順。標準起動コマンドは `uv run robopen-agent` とし、systemdでSSH切断後とRaspberry Pi再起動後の自動復旧を担保する。

## 1. 前提

- Raspberry PiへMacからSSHできること。
- Raspberry Pi上に `git`、`uv`、Codex CLIがインストール済みであること。
- Slack AppはSocket Modeを使うため、Raspberry Pi側のポート開放は不要。
- 実tokenを含む `.env` はRaspberry Pi上で作成し、リポジトリへコミットしない。

## 2. 配置

MacからRaspberry PiへSSHする。

```sh
ssh <user>@<raspberry-pi-host>
```

標準配置先は `/home/<user>/robopen-agent-py` とする。

```sh
cd /home/<user>
git clone <repo-url> robopen-agent-py
cd /home/<user>/robopen-agent-py
uv sync
cp .env.example .env
```

`.env` に本番用の値を設定する。

```dotenv
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
CODEX_CMD=/home/<user>/.local/bin/codex
CODEX_WORKSPACE_DIR=/home/<user>/robopen-workspace
CODEX_SANDBOX=workspace-write
CODEX_SKIP_GIT_REPO_CHECK=false
SQLITE_PATH=data/agent.db
SLACK_LOG_CHANNEL=C0123456789
PROACTIVE_ENABLED=false
PROACTIVE_CHANNEL=C0123456789
PROACTIVE_TIMES_PER_DAY=4
PROACTIVE_WINDOW_START=09:00
PROACTIVE_WINDOW_END=22:00
PROACTIVE_MIN_GAP_MINUTES=120
PROACTIVE_TIMEZONE=Asia/Tokyo
```

実際のユーザー名、`uv` のパス、repo pathを確認する。

```sh
whoami
which uv
pwd
```

以降の例では以下を前提にする。

- user: `<user>`
- repo path: `/home/<user>/robopen-agent-py`
- uv path: `/home/<user>/.local/bin/uv`

実環境で異なる場合は、systemd unit内の `User`、`WorkingDirectory`、`ExecStart`、`EnvironmentFile` を置き換える。

Codexにruntime workspaceへ書き込ませる場合は、Linux権限とCodex sandboxの両方を確認する。

```sh
mkdir -p /home/<user>/robopen-workspace
touch /home/<user>/robopen-workspace/write-test.txt
rm /home/<user>/robopen-workspace/write-test.txt
```

`touch` が失敗する場合は所有者を修正する。

```sh
sudo chown -R <user>:<user> /home/<user>/robopen-workspace
```

runtime workspaceをgit管理しない場合は `.env` で `CODEX_SKIP_GIT_REPO_CHECK=true` にする。`git init` 済みなら `false` のままでよい。

## 3. 手動疎通確認

systemd化する前に、SSHセッション上で起動してSlack疎通を確認する。

```sh
cd /home/<user>/robopen-agent-py
uv run robopen-agent
```

SlackのDMまたはメンションで1往復できることを確認したら、`Ctrl+C` で停止する。

一時的な検証だけなら `tmux` で起動してもよい。ただし本番運用はsystemdを標準とする。

## 4. systemd service 登録

テンプレートをコピーして、実ユーザー名とパスを置換する。

```sh
sudo cp deploy/robopen-agent.service.example /etc/systemd/system/robopen-agent.service
sudo nano /etc/systemd/system/robopen-agent.service
```

最低限、以下を実環境に合わせる。

- `User=<user>`
- `WorkingDirectory=/home/<user>/robopen-agent-py`
- `ExecStart=/home/<user>/.local/bin/uv run robopen-agent`
- `EnvironmentFile=/home/<user>/robopen-agent-py/.env`

登録して起動する。

```sh
sudo systemctl daemon-reload
sudo systemctl enable robopen-agent
sudo systemctl start robopen-agent
```

状態確認。

```sh
sudo systemctl status robopen-agent
```

ログ確認。

```sh
journalctl -u robopen-agent -f
```

## 5. 運用コマンド

停止。

```sh
sudo systemctl stop robopen-agent
```

再起動。

```sh
sudo systemctl restart robopen-agent
```

serviceファイルを変更した場合。

```sh
sudo systemctl daemon-reload
sudo systemctl restart robopen-agent
```

アプリ更新時。

```sh
cd /home/<user>/robopen-agent-py
git pull
uv sync
sudo systemctl restart robopen-agent
```

## 6. SQLiteバックアップ

標準DBは `SQLITE_PATH=data/agent.db`。SQLiteはWALを使うため、バックアップ時はDB本体だけでなく `agent.db-wal` と `agent.db-shm` が存在する場合も同じタイミングで保全する。

簡易バックアップ例。

```sh
mkdir -p /home/<user>/robopen-agent-backups
sqlite3 /home/<user>/robopen-agent-py/data/agent.db ".backup '/home/<user>/robopen-agent-backups/agent-$(date +%Y%m%d).db'"
```

復元時はserviceを停止してからDBを差し替える。

```sh
sudo systemctl stop robopen-agent
cp /home/<user>/robopen-agent-backups/agent-YYYYMMDD.db /home/<user>/robopen-agent-py/data/agent.db
sudo systemctl start robopen-agent
```

## 7. 緊急時の代替起動

systemd設定前の短時間検証は `tmux` を使える。

```sh
tmux new -s robopen-agent
cd /home/<user>/robopen-agent-py
uv run robopen-agent
```

detachは `Ctrl+b` の後に `d`。再接続は以下。

```sh
tmux attach -t robopen-agent
```

`nohup` はプロセス落ちの自動復旧がないため、常駐運用では使わない。
