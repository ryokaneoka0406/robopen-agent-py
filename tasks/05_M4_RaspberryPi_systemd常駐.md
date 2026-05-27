# M4 Raspberry Pi常駐: systemd本番デプロイ

## タスクの内容
- Raspberry Pi上にリポジトリを配置し、`uv run robopen-agent` で手動疎通できる状態にする。
- `robopen-agent.service` をsystemdに登録し、SSH切断後・Raspberry Pi再起動後もSlack疎通機能が常駐するようにする。
- `.env` を `EnvironmentFile` として読み込み、Slack token / Codex / SQLite / Slack通知チャンネル設定をsystemd起動時に注入する。
- journaldでログ確認できるようにし、`status` / `restart` / `stop` / service更新時の手順を文書化する。
- SQLite日次バックアップと復元手順を文書化する。

## ステータス
- TODO

## 成果物
- `documents/raspberry-pi-systemd.md`
- `deploy/robopen-agent.service.example`

## 完了条件
- Raspberry Pi上で `uv run robopen-agent` による手動疎通確認ができる。
- `sudo systemctl enable --now robopen-agent` 後、SSHを切ってもSlack DM/メンションに応答する。
- Raspberry Pi再起動後もserviceが自動起動する。
- `journalctl -u robopen-agent -f` でログを追跡できる。
- `data/agent.db` のバックアップと復元手順が確認できる。
