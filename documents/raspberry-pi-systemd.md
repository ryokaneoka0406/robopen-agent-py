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
CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=false
CODEX_SKIP_GIT_REPO_CHECK=false
SLACK_FILE_ROOT=/home/<user>/robopen-workspace/share
SLACK_FILE_MAX_BYTES=20971520
SQLITE_PATH=data/agent.db
SLACK_LOG_CHANNEL=C0123456789
PROACTIVE_ENABLED=false
PROACTIVE_CHANNEL=C0123456789
PROACTIVE_TIMES_PER_DAY=4
PROACTIVE_WINDOW_START=09:00
PROACTIVE_WINDOW_END=22:00
PROACTIVE_MIN_GAP_MINUTES=120
PROACTIVE_TIMEZONE=Asia/Tokyo
HEALTH_UPLOAD_ENABLED=false
HEALTH_UPLOAD_HOST=127.0.0.1
HEALTH_UPLOAD_PORT=8787
HEALTH_UPLOAD_TOKEN_HASH=<sha256-of-health-upload-token>
HEALTH_UPLOAD_MAX_BYTES=20971520
HEALTH_UPLOAD_MAX_UNCOMPRESSED_BYTES=104857600
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

非対話運用でCodexの承認待ちやsandbox制約を完全に外す場合のみ、`.env` で `CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=true` にする。この設定は `--dangerously-bypass-approvals-and-sandbox` を付与し、`CODEX_SANDBOX` より優先されるため、専用ユーザー・専用workspace・OS側の権限制限がある環境に限定する。

Slackへworkspaceファイルをアップロードする場合は、Slack AppのBot Token Scopesに `files:write` を追加し、アプリを再インストールする。送信対象は `SLACK_FILE_ROOT` 配下に限定されるため、運用前に専用ディレクトリを作成する。

```sh
mkdir -p /home/<user>/robopen-workspace/share
```

ヘルスケアiPhoneアプリからのアップロードを受ける場合は、receiver用tokenを作成し、Pi側にはSHA-256だけを保存する。

```sh
python3 - <<'PY'
import hashlib, secrets
token = secrets.token_urlsafe(32)
print("token:", token)
print("HEALTH_UPLOAD_TOKEN_HASH=" + hashlib.sha256(token.encode()).hexdigest())
PY
```

iPhoneアプリには `token:` の値、Piの `.env` には `HEALTH_UPLOAD_TOKEN_HASH=...` を設定する。`HEALTH_UPLOAD_ROOT` 未設定時は `CODEX_WORKSPACE_DIR/healthcare` が保存先になる。

## 3. 手動疎通確認

systemd化する前に、SSHセッション上で起動してSlack疎通を確認する。

```sh
cd /home/<user>/robopen-agent-py
uv run robopen-agent
```

SlackのDMまたはメンションで1往復できることを確認したら、`Ctrl+C` で停止する。

ヘルスケアreceiverを使う場合は別terminalで手動疎通する。

```sh
cd /home/<user>/robopen-agent-py
HEALTH_UPLOAD_ENABLED=true uv run robopen-health-receiver
```

別terminalからhealth checkを確認する。

```sh
curl http://127.0.0.1:8787/healthz
```

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

## 5. Health Upload Receiver

receiverはSlack/Codex本体から独立したsystemd serviceとして登録する。

```sh
sudo cp deploy/robopen-health-receiver.service.example /etc/systemd/system/robopen-health-receiver.service
sudo nano /etc/systemd/system/robopen-health-receiver.service
```

最低限、以下を実環境に合わせる。

- `User=<user>`
- `WorkingDirectory=/home/<user>/robopen-agent-py`
- `ExecStart=/home/<user>/.local/bin/uv run robopen-health-receiver`
- `EnvironmentFile=/home/<user>/robopen-agent-py/.env`

`.env` でreceiverを有効化する。

```dotenv
HEALTH_UPLOAD_ENABLED=true
HEALTH_UPLOAD_HOST=127.0.0.1
HEALTH_UPLOAD_PORT=8787
HEALTH_UPLOAD_TOKEN_HASH=<sha256-of-health-upload-token>
HEALTH_UPLOAD_MAX_BYTES=20971520
HEALTH_UPLOAD_MAX_UNCOMPRESSED_BYTES=104857600
```

登録して起動する。

```sh
sudo systemctl daemon-reload
sudo systemctl enable robopen-health-receiver
sudo systemctl start robopen-health-receiver
sudo systemctl status robopen-health-receiver
```

Tailscale Serveでtailnet内HTTPSとして公開する。手動確認だけなら次を実行する。

```sh
sudo tailscale serve --yes --bg --https=443 http://127.0.0.1:8787
```

常時運用では、Tailscale Serveもsystemd unitとして登録する。これによりPi再起動後に `https://<pi-hostname>.<tailnet-name>.ts.net` からreceiverへ到達できる状態を復元する。

```sh
sudo cp deploy/robopen-health-tailscale-serve.service.example /etc/systemd/system/robopen-health-tailscale-serve.service
sudo systemctl daemon-reload
sudo systemctl enable robopen-health-tailscale-serve
sudo systemctl start robopen-health-tailscale-serve
sudo systemctl status robopen-health-tailscale-serve
```

Serve設定を確認する。

```sh
sudo tailscale serve status
```

iPhoneアプリのEndpointは次の形式にする。

```text
https://<pi-hostname>.<tailnet-name>.ts.net/v1/health/imports
```

Tailscale Funnelは使わない。アップロードされたファイルは `CODEX_WORKSPACE_DIR/healthcare/inbox/YYYY/MM/DD/<export-id>.json.deflate` に保存される。

`listener already exists for port 443` が出る場合は、古いforegroundの `tailscale serve` が残っているか、既存のServe設定が競合している。まず次で状態を見る。

```sh
ps aux | grep '[t]ailscale serve'
sudo tailscale serve status
```

このPiで他のTailscale Serveを使っていない場合のみ、設定を消してから入れ直す。

```sh
sudo tailscale serve reset
sudo systemctl restart robopen-health-tailscale-serve
```

## 6. 運用コマンド

停止。

```sh
sudo systemctl stop robopen-agent
```

## 7. Grafana CloudへのRaspberry Piログ送信

Raspberry Pi本体の故障検知と切り分けのため、Grafana CloudのRaspberry Pi integrationを使い、Grafana Alloyからメトリクスとログを送信する。Alloyは各Raspberry Pi上に1つずつ常駐させる。

送信対象はGrafana CloudのRaspberry Pi integrationが生成する公式Alloy設定に従う。

- node exporter相当のOSメトリクス: CPU、load、memory、disk、network、filesystem、temperature、systemd unit stateなど。
- journaldまたはOSログ: `robopen-agent`、`robopen-health-receiver`、`tailscaled`、kernel、systemdを含むRaspberry Pi本体ログ。

Grafana Cloud側では、対象stackで `Connections` -> `Raspberry Pi` を開き、integrationをInstallする。`Configuration details` タブで以下を行う。

1. `Select platform` はRaspberry Pi OSに合わせる。標準は `Debian` / `Arm64`。
2. `Run Grafana Alloy` を開き、`Create a new token` でAlloy用tokenを作成する。Token nameは `robopen-raspi-alloy`、scopeは画面既定の `set:alloy-data-write`、expirationは個人運用では `No expiry` を標準にする。
3. `Enable Remote Configuration` を有効にする。Fleet Managementからcollectorの疎通と設定を管理できるため、Grafana Cloud画面の `Test Alloy connection` と合わせやすい。
4. `Install and run Grafana Alloy` に表示されるコマンドを `Copy to clipboard` でコピーする。

Raspberry Pi側では、Grafana Cloud画面からコピーした公式コマンドをそのまま実行する。リポジトリではAlloyの独自設定ファイルや独自wrapper scriptを管理しない。公式コマンドは概ね以下の形式になるが、実際にはGrafana Cloud画面で生成されたものを使う。

```sh
GCLOUD_HOSTED_METRICS_ID="<metrics-instance-id>" \
GCLOUD_HOSTED_METRICS_URL="https://prometheus-prod-XX-prod-region.grafana.net/api/prom/push" \
GCLOUD_HOSTED_LOGS_ID="<logs-instance-id>" \
GCLOUD_HOSTED_LOGS_URL="https://logs-prod-XXX.grafana.net/loki/api/v1/push" \
GCLOUD_FM_URL="https://fleet-management-prod-XXX.grafana.net" \
GCLOUD_FM_POLL_FREQUENCY="60s" \
GCLOUD_FM_HOSTED_ID="<fleet-management-hosted-id>" \
ARCH="arm64" \
GCLOUD_RW_API_KEY="<grafana-cloud-access-policy-token>" \
/bin/sh -c "$(curl -fsSL https://storage.googleapis.com/cloud-onboarding/alloy/scripts/install-linux.sh)"
```

`GCLOUD_RW_API_KEY` はGrafana CloudのAlloy用tokenを使う。実tokenはリポジトリ、`.env`、systemd unit、運用ドキュメントに書かない。Grafana Cloud画面からコピーしたコマンドをRaspberry Pi上のshellで直接実行する。

過去にrobopen独自のGrafana Alloy設定を入れたRaspberry Piでは、公式コマンド実行前に独自drop-inを消す。

```sh
sudo systemctl stop alloy || true
sudo rm -f /etc/systemd/system/alloy.service.d/robopen-grafana-cloud.conf
sudo systemctl daemon-reload
```

公式コマンド実行後、Alloyを再起動して状態を確認する。

```sh
sudo systemctl enable --now alloy
sudo systemctl restart alloy
```

状態確認。

```sh
sudo systemctl status alloy
journalctl -u alloy -f
```

Grafana Cloud上では、Raspberry Pi integrationの以下のdashboardで確認する。

- `Raspberry Pi / overview`
- `Raspberry Pi / logs`

ログ探索では、まず以下のようなLoki labelで絞る。

```logql
{job="integrations/raspberrypi-node", instance="<raspberry-pi-hostname>"}
```

robopen-agentだけを見る場合。

```logql
{job="integrations/raspberrypi-node", unit="robopen-agent.service"}
```

障害時の切り分け。

- `journalctl -u alloy -n 200 --no-pager` でAlloy自身の送信エラーを確認する。
- `sudo systemctl cat alloy` と `sudo sed -n '1,220p' /etc/alloy/config.alloy` で、Grafana Cloudの公式onboarding scriptが生成したservice/configになっていることを確認する。
- `failed to tail the file: permission denied` が `/var/log/*.log` で出る場合、`id alloy` で `adm` グループが含まれていることを確認し、`sudo usermod -aG adm alloy && sudo systemctl restart alloy` を実行する。journald送信だけでも最低限の運用ログは追える。
- Grafana Cloud側でデータが見えない場合、画面の `Install and run Grafana Alloy` に表示される公式コマンド、token scope、stackのregion、Remote ConfigurationのON/OFFを再確認する。

再起動。

```sh
sudo systemctl restart robopen-agent
```

serviceファイルを変更した場合。

```sh
sudo systemctl daemon-reload
sudo systemctl restart robopen-agent
```

receiverの再起動。

```sh
sudo systemctl restart robopen-health-receiver
```

Tailscale Serve設定の再適用。

```sh
sudo systemctl restart robopen-health-tailscale-serve
sudo tailscale serve status
```

アプリ更新時。

```sh
cd /home/<user>/robopen-agent-py
git pull
uv sync
sudo systemctl restart robopen-agent
```

receiverのログ確認。

```sh
journalctl -u robopen-health-receiver -f
```

Tailscale Serve unitの状態確認。

```sh
sudo systemctl status robopen-health-tailscale-serve
```

## 8. SQLiteバックアップ

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

## 9. 緊急時の代替起動

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
