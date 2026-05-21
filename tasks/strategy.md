# タスク並行実行戦略

## 並行実行可能な組み合わせ

- 01_M0_PoC_SLACK疎通 と 02_M1_SQLite永続化
  - インターフェース合意（session_managerのI/O）を先に決めれば、Slack疎通とDB層を並行実装可能。
- 05_M4_VPSデプロイ と 06_M5_スキル拡張
  - アプリ本体の機能凍結後は、インフラ整備とスキル追加を別担当で平行可能。
- 07_横断_安全性と運用設計
  - 全フェーズ横断だが、初期ドラフトはM0時点から進められる。各マイルストーン完了時に追記レビューする。
- 04_M3_承認フロー実装 は 08_M6_Codex_app-server移行 完了後に再開する（並行不可）。
- 09_M7_Claude_Code_Codex両対応 は既存の `codex exec` 経路を残すadapter追加のため、M6とは独立して先行可能。

## 依存関係の推奨順序

1. 01_M0_PoC_SLACK疎通
2. 02_M1_SQLite永続化
3. 03_M2_スケジューラ実装
4. 05_M4_VPSデプロイ + 06_M5_スキル拡張（並行）
5. 08_M6_Codex_app-server移行
6. 09_M7_Claude_Code_Codex両対応
7. 04_M3_承認フロー実装（M6 完了後に再設計反映で再開）
8. 07_横断_安全性と運用設計（全期間継続）


## 進捗メモ
- 2026-05-10: `03_M2_スケジューラ実装` を完了（cron/one-shot登録、起動時リストア、Slack通知実装）。
- 2026-05-14: `04_M3_承認フロー実装` のラッパー側ルールベース実装案（PR #14）をクローズ。承認ゲートは Codex app-server の `approvalPolicy: "on-request"` を Slack に橋渡しする方式へ再設計予定。新規タスク `08_M6_Codex_app-server移行` を起こし、M3 はそれが完了するまで BLOCKED。
- 2026-05-21: `09_M7_Claude_Code_Codex両対応` を追加。Codex app-server移行を待たず、CLI adapter方式でClaude Codeを追加する。
