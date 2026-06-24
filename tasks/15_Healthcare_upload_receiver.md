# Healthcare upload receiver

## タスクの内容
- iPhone Healthcare SyncアプリからTailscale経由でPOSTされるdeflate済みHealthKit export payloadを受け取る。
- Slack/Codex本体とは独立した `robopen-health-receiver` コマンドとして起動できるようにする。
- bearer token hash、Content-Type、Content-Encoding、export id、payload SHA-256、schemaVersionを検証する。
- 受け取ったpayloadを `CODEX_WORKSPACE_DIR/healthcare/inbox/YYYY/MM/DD/<export-id>.json.deflate` へatomicに配置する。
- systemdとTailscale Serveの運用手順を文書化する。

## ステータス
- DONE

## 成果物
- `robopen_agent/health_receiver.py`
- `deploy/robopen-health-receiver.service.example`
- `tests/test_health_receiver.py`
- `documents/designdoc.md`
- `documents/raspberry-pi-systemd.md`

## 完了条件
- `uv run robopen-health-receiver` でlocalhost receiverを起動できる。
- `GET /healthz` がreceiver情報を返す。
- 正常なdeflate payloadがworkspaceのhealthcare inboxへ保存される。
- token不備、hash不一致、bad deflate、invalid JSON、schema不一致、重複conflictを拒否できる。
- `uv run pytest` が通る。
