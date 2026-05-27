# M6 Codex app-server 移行と承認フロー再設計

## タスクの内容
- `runCodex` を `codex exec`（非対話プロセス起動）から Codex app-server / MCP 接続ベースに置き換える。
- `thread/start` で `approvalPolicy: "on-request"`、`sandbox: "workspace-write"` を指定し、Codex が発火する approval 要求イベントを受け取れるようにする。
- approval 要求イベントを Slack の Block Kit ボタン（Approve / Deny）に橋渡しし、ユーザー判断を Codex に返却する経路を実装する。
- タイムアウト時の自動キャンセルとSlackスレッド上の承認イベント記録（`approval_requested` / `approval_approved` / `approval_denied` / `approval_timeout`）を実装する。
- 既存の会話履歴／`sessionId` 管理ロジックを app-server スレッドに合わせて再構成する。

## 現状仕様
- Slack Socket Mode で DM / mention を受け、Wrapper が `runCodex()` を呼び出す。
- 現在の `runCodex()` は `codex exec --json --output-last-message -` をサブプロセス起動し、stdout JSONL から `thread_id` を拾って `sessionId` として返す。
- Slack thread ごとに SQLite の `conversations` レコードを作り、`codex_rollout_id` を次回の `codex exec resume` に渡す。
- 承認フローは未実装。M3 は BLOCKED で、ユーザー入力文字列への正規表現マッチによる削除系検出案（PR #14）は不採用。

## 移行判断
- M6 の主目的が「Slack 承認を実コマンド単位で正しく挟むこと」であるため、`codex exec` 継続より `codex app-server` 移行の方が設計として妥当。
- Wrapper 側で入力文を検査する方式では、自然文中の `delete` 等による誤検知と、Codex が実行段階で生成する `rm` / `unlink` 等の見逃しを同時に避けられない。
- app-server の approval event を Slack に橋渡しすれば、承認対象を「ユーザー入力」ではなく「Codex が実行しようとしている操作」にできる。
- ただし `codex app-server` は `codex-cli 0.128.0` 時点で experimental のため、全面的に密結合せず、薄い adapter 層を挟んで段階移行する。

## メリット
- `item/commandExecution/requestApproval` / `item/fileChange/requestApproval` を受け取り、実コマンド・ファイル変更単位で Slack 承認 UI を出せる。
- `thread/start` / `turn/start` で `approvalPolicy: "on-request"`、sandbox、approval reviewer を指定できる。
- 常駐サーバー化により、毎回 `codex exec` を起動するレイテンシやプロセス管理の粗さを下げられる可能性がある。
- turn / item / token usage / diff / output delta などのイベントを拾えるため、Slack への進捗表示やSQLite上のSlack作業ログを精密化できる。

## デメリット・リスク
- app-server プロトコルは experimental で変更リスクがある。CLI バージョン固定と protocol adapter が必要。
- `codex exec` の単発実行より実装量が増える。JSON-RPC、request/response 相関、server request への応答、再接続処理が必要。
- Slack interactive button の二重クリック、approval 待ち中のタイムアウト、Codex 側への `accept` / `decline` / `cancel` 返却を正しく扱う必要がある。
- VPS 運用では app-server 常駐プロセスの監視、socket 保護、auth token、再起動時の thread 復元が追加で必要。

## 実装方針メモ
- まず `CodexClient` adapter を追加し、既存呼び出し側には `runCodex(prompt, sessionId)` 相当のインターフェースを維持する。
- adapter 内部で app-server を起動・接続し、既存の `codex_rollout_id` は app-server の `threadId` として扱う。
- 新規会話は `thread/start`、既存会話は `thread/resume` または保持済み thread への `turn/start` を使う。
- `turn/start` 側で sandbox を指定する場合は `sandboxPolicy: { type: "workspaceWrite", ... }` 形式になる点に注意する。
- approval request を受けたら Slack Block Kit に command / cwd / reason / 対象 thread を表示し、Approve は `accept`、Deny は `decline`、タイムアウトは `cancel` を返す。
- protocol 型は `codex app-server generate-ts` で生成できるが、生成物を直接広範囲に依存させず、必要最小限の型だけ adapter 境界に閉じ込める。

## 完了条件
- ユーザー入力テキストへの正規表現マッチに依存せず、Codex が実行しようとする削除系コマンドに対して必ず Slack 承認 UI が出ること。
- Approve / Deny / タイムアウト の各経路でSlackスレッドに記録が残り、その投稿がSQLiteの作業ログとして保存されること。
- M3 の完了条件「rm系操作で必ず確認が走る」を実コマンド単位で満たすこと。
- 既存の Slack 会話継続と Scheduler 実行が app-server 移行後も壊れないこと。
- app-server 依存箇所が adapter に閉じており、CLI プロトコル変更時の修正範囲が限定されていること。

## ステータス
- TODO

## 前提・依存
- M5（スキル拡張）完了後に着手する。
- 完了後に M3（承認フロー実装）の再開可否を判断する。

## 参考
- `documents/designdoc.md` の M3 完了条件。
- Codex CLI ドキュメント（`thread/start` の `approvalPolicy` / `sandbox`、`~/.codex/config.toml` の `approval_policy` / `sandbox_mode`）。
- クローズ済み PR #14 のレビュー履歴（ルールベース実装の不採用理由）。
