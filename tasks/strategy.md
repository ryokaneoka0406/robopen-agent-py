# タスク並行実行戦略

## 並行実行可能な組み合わせ

- 01_M0_PoC_SLACK疎通 と 02_M1_SQLite永続化
  - インターフェース合意（session_managerのI/O）を先に決めれば、Slack疎通とDB層を並行実装可能。
- 05_M4_RaspberryPi_systemd常駐 と 06_M5_スキル拡張
  - アプリ本体の機能凍結後は、インフラ整備とスキル追加を別担当で平行可能。
- 07_横断_安全性と運用設計
  - 全フェーズ横断だが、初期ドラフトはM0時点から進められる。各マイルストーン完了時に追記レビューする。
- 04_M3_承認フロー実装 は 08_M6_Codex_app-server移行 完了後に再開する（並行不可）。
- 09_M2拡張_デフォルト自発発話 は M2 の既存Schedulerを使うため、M4常駐運用と並行して改善可能。
- 11_WorkspaceファイルSlack送信 は Slack連携の拡張であり、Codex app-server移行とは独立して実装可能。ただし `files:write` scope追加と運用手順更新が必要。

## 依存関係の推奨順序

1. 01_M0_PoC_SLACK疎通
2. 02_M1_SQLite永続化
3. 03_M2_スケジューラ実装
4. 05_M4_RaspberryPi_systemd常駐 + 06_M5_スキル拡張（並行）
5. 08_M6_Codex_app-server移行
6. 04_M3_承認フロー実装（M6 完了後に再設計反映で再開）
7. 07_横断_安全性と運用設計（全期間継続）
8. 11_WorkspaceファイルSlack送信（M0/M1完了後なら独立実装可能）


## 進捗メモ
- 2026-05-10: `03_M2_スケジューラ実装` を完了（cron/one-shot登録、起動時リストア、Slack通知実装）。
- 2026-05-14: `04_M3_承認フロー実装` のラッパー側ルールベース実装案（PR #14）をクローズ。承認ゲートは Codex app-server の `approvalPolicy: "on-request"` を Slack に橋渡しする方式へ再設計予定。新規タスク `08_M6_Codex_app-server移行` を起こし、M3 はそれが完了するまで BLOCKED。
- 2026-05-28: M4の本番運用前提をRaspberry Pi/systemd/uvへ変更。標準起動コマンドは `uv run robopen-agent`。
- 2026-05-28: `09_M2拡張_デフォルト自発発話` を追加。`.env` で有効化した場合に1日4回程度のproactive one-shot taskを自動生成する。
- 2026-06-01: `11_WorkspaceファイルSlack送信` を追加。`workspace/share/` 配下のファイルを自然文またはCodexマニフェストからSlackへアップロードする。
- 2026-06-12: `13_統合テスト項目整備` を完了。現時点の実装を対象に、正常系・異常系・OS差分を `documents/integration-test-plan.md` へ整理した。
