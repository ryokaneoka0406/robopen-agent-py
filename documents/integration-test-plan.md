# 統合テスト項目書

## 1. 目的

Slack、Wrapper、Codex CLI、SQLite、Scheduler、workspaceファイル連携を実環境に近い構成で接続し、現時点で実装済みの機能が一連のフローとして動作することを確認する。

本書は正常系、異常系、再起動・永続化、セキュリティ境界、OS差分を対象とする。単体テストの関数レベルの確認は重複させず、外部境界をまたぐ振る舞いを重点的に確認する。

## 2. 対象範囲

### 2.1 合否判定対象

| 機能 | 実装状態 | 主な確認対象 |
| --- | --- | --- |
| Slack Socket Mode受信 | 実装済み | DM、メンション、追跡済みスレッド、重複イベント |
| Codex CLI実行 | 実装済み | 新規実行、session resume、workspace、sandbox設定、異常終了 |
| SQLite作業ログ | 実装済み | conversations、messages、tasks、再起動後の復元、WAL |
| Scheduler | 実装済み | cron、one-shot、一覧、更新、確認付き取消、実行結果通知 |
| 自然文スケジュール操作 | 実装済み | 登録、更新、削除対象抽出、曖昧性、低confidence |
| デフォルト自発発話 | 実装済み | 日次生成、重複防止、通知、会話継続 |
| workspaceファイル送信 | 実装済み | コマンド、自然文、Codexマニフェスト、パス制約、監査ログ |
| Slack添付ファイル受信 | 実装済み | private URL取得、保存、Codexへのメタデータ連携、サイズ制約 |
| macOSローカル起動 | 実装済み | `uv`、相対パス、ローカルファイル権限 |
| Raspberry Pi OS/Linux常駐 | 手順・unitあり、実機完了待ち | systemd、journald、自動再起動、再起動後復元、バックアップ |

### 2.2 合否判定対象外

以下は設計またはタスクに記載があるが、現時点では未実装または完了待ちである。統合テスト実施時は「未実装」と記録し、不具合として扱わない。

| 機能 | 状態 | 関連タスク |
| --- | --- | --- |
| Codex実コマンド単位のApprove / Deny / timeout | BLOCKED | M3、M6 |
| Codex app-server / MCP移行 | TODO | M6 |
| conversation要約、60%ロールオーバー、24時間要約 | 未実装 | 設計書 5.3 |
| Codex利用上限監視と自動スキップ | TODO | 横断タスク |
| MemoryHigh / MemoryMax、日次再起動 | TODO | 横断タスク |
| skill自動生成と実用skill 2～3本 | TODO | M5 |
| Windows本番運用 | 非サポート | 非ゴール相当 |

## 3. テスト環境

### 3.1 必須環境

| 環境ID | OS | 用途 | 必須 |
| --- | --- | --- | --- |
| ENV-MAC | macOS、現行サポート版 | 開発・ローカル統合確認 | 必須 |
| ENV-LINUX | Raspberry Pi OS 64-bit / Debian系Linux | 本番相当、systemd確認 | 必須 |
| ENV-WIN | Windows 11 | 参考互換性確認のみ | 任意 |

共通前提:

- Python 3.11以上
- `uv`
- Codex CLI
- Socket Mode有効のテスト用Slack App
- Bot Token Scopesは利用機能に応じてメッセージ受信・投稿、`files:write`、添付取得に必要な権限を付与する
- 本番データと分離したSlackチャンネル、SQLite DB、workspaceを使用する
- テスト中に危険バイパスを有効にする場合は、破棄可能な専用workspaceとOSユーザーを使用する

### 3.2 基準設定

```dotenv
SLACK_BOT_TOKEN=xoxb-test-...
SLACK_APP_TOKEN=xapp-test-...
CODEX_CMD=codex
CODEX_WORKSPACE_DIR=<absolute-test-workspace>
CODEX_SANDBOX=workspace-write
CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=false
CODEX_SKIP_GIT_REPO_CHECK=true
SQLITE_PATH=<absolute-test-data>/agent.db
SLACK_LOG_CHANNEL=<test-channel-id>
SLACK_FILE_ROOT=<absolute-test-workspace>/share
SLACK_FILE_MAX_BYTES=20971520
SLACK_INBOUND_FILE_ROOT=<absolute-test-workspace>/inbox/slack
SLACK_INBOUND_FILE_MAX_BYTES=20971520
PROACTIVE_ENABLED=false
PROACTIVE_CHANNEL=<test-channel-id>
PROACTIVE_TIMES_PER_DAY=4
PROACTIVE_WINDOW_START=09:00
PROACTIVE_WINDOW_END=22:00
PROACTIVE_MIN_GAP_MINUTES=120
PROACTIVE_TIMEZONE=Asia/Tokyo
```

### 3.3 テストデータ

- `share/report.md`: 小容量のUTF-8 Markdown
- `share/images/chart.png`: 小容量のPNG
- `share/a/report.md`、`share/b/report.md`: 同名ファイルの曖昧性確認用
- `share/.secret`: 隠しファイル
- `share/large.bin`: `SLACK_FILE_MAX_BYTES` 超過ファイル
- workspace外の `secret.txt` と、可能なOSではそこを指す `share/link.txt`
- Slack添付用の小容量テキスト、画像、上限超過ファイル

## 4. 判定と証跡

- 結果は `PASS`、`FAIL`、`BLOCKED`、`N/A` のいずれかで記録する。
- Slack画面、実行ログ、SQLite照会結果、保存ファイル、systemd状態を証跡として残す。
- 時刻比較は、DBとScheduler内部はUTC、ユーザー表示はJSTであることを分けて確認する。
- Slack Event APIの再送は起こり得るため、同じ `event_id` または同じ投稿 `channel:ts` による重複登録の有無を確認する。
- OS固有でない項目はENV-MACで一巡し、ファイル・プロセス・常駐・再起動に関係する項目をENV-LINUXで再実施する。

## 5. 正常系テスト

### 5.1 起動・Slack受信・通常会話

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-001 | 依存関係同期 | `uv sync` を実行する | エラーなく仮想環境と依存関係が準備される | MAC / LINUX |
| IT-N-002 | コンソールスクリプト起動 | `uv run robopen-agent` を実行する | Socket Mode接続が開始し、プロセスが継続稼働する | MAC / LINUX |
| IT-N-003 | module起動 | `uv run python -m robopen_agent` を実行する | IT-N-002と同等に起動する | MAC / LINUX |
| IT-N-004 | Slack DM応答 | Botへ通常文をDMする | Codex応答がDMに返り、user/assistantメッセージがDBへ保存される | MAC / LINUX |
| IT-N-005 | チャンネルメンション応答 | テストチャンネルでBotをメンションする | 元投稿のスレッドに応答する | MAC / LINUX |
| IT-N-006 | DM継続会話 | 同じDMで前発言を参照する質問を送る | 保存済みsession IDで `codex exec resume` され、文脈を踏まえた応答になる | MAC / LINUX |
| IT-N-007 | メンションスレッド継続 | IT-N-005のスレッドでメンションなしに返信する | 追跡済みスレッドとして処理され、同じconversationを再利用する | MAC / LINUX |
| IT-N-008 | 別スレッド分離 | 同一チャンネルで別の新規メンションを送る | 異なるconversationとCodex sessionとして扱われる | MAC / LINUX |
| IT-N-009 | ユーザーメンション付き応答 | チャンネルでメンションする | Bot応答本文の先頭に依頼ユーザーへのメンションが付く | MAC / LINUX |
| IT-N-010 | Bot投稿の無視 | Bot自身または別Botが投稿する | Codexを実行せず、応答・DB追加を行わない | MAC / LINUX |
| IT-N-011 | 未追跡チャンネルスレッドの無視 | Botが開始していない通常投稿のスレッドへメンションなしで投稿する | Codexを実行せず応答しない | MAC / LINUX |
| IT-N-012 | event重複抑止 | 同一 `event_id` のイベントを再送する | 2回目は処理されず、応答・タスク・メッセージが重複しない | MAC / LINUX |

### 5.2 Codex CLI・workspace・session

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-020 | 既定workspace | `CODEX_WORKSPACE_DIR` を未設定で会話する | リポジトリ直下 `workspace/` が作成・利用される | MAC / LINUX |
| IT-N-021 | 絶対workspace | 絶対パスを設定してファイル作成を依頼する | 指定ディレクトリをcwdとしてCodexが動作する | MAC / LINUX |
| IT-N-022 | 相対workspace | `CODEX_WORKSPACE_DIR=integration-workspace` で起動する | リポジトリルート基準で解決される | MAC / LINUX |
| IT-N-023 | workspace-write | `CODEX_SANDBOX=workspace-write` でworkspace内ファイル作成を依頼する | workspace内へ書き込みできる | MAC / LINUX |
| IT-N-024 | read-only | `CODEX_SANDBOX=read-only` で書き込みを伴わない質問を送る | 正常応答し、workspaceへ変更を加えない | MAC / LINUX |
| IT-N-025 | git確認スキップ | 非git workspaceで `CODEX_SKIP_GIT_REPO_CHECK=true` にする | git repository checkで失敗せず実行できる | MAC / LINUX |
| IT-N-026 | session ID永続化 | 初回会話後にDBを確認する | `conversations.codex_rollout_id` にCodexのthread IDが保存される | MAC / LINUX |
| IT-N-027 | プロセス再起動後resume | アプリを停止・再起動し、既存Slackスレッドへ返信する | SQLiteからsession IDを復元し会話を継続する | MAC / LINUX |
| IT-N-028 | 空のCodex最終応答 | Codexが空の最終応答を返す条件を作る | Slackには `(empty response)` が返る | MAC / LINUX |

### 5.3 SQLite永続化

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-030 | 初回スキーマ作成 | 空のDBパスで起動する | `conversations`、`messages`、`tasks` が作成され、WALが有効になる | MAC / LINUX |
| IT-N-031 | DB親ディレクトリ作成 | 存在しない親ディレクトリを含む `SQLITE_PATH` で起動する | 親ディレクトリとDBが作成される | MAC / LINUX |
| IT-N-032 | conversation一意性 | 同じSlackスレッドで複数回会話する | `slack_thread_ts` ごとにconversationが1件だけ存在する | MAC / LINUX |
| IT-N-033 | message順序とrole | 2往復会話後にDBを照会する | user/assistantの内容と作成順が保持される | MAC / LINUX |
| IT-N-034 | `last_active_at` 更新 | 同じconversationへ追加投稿する | `last_active_at` が新しいUTC時刻へ更新される | MAC / LINUX |
| IT-N-035 | 旧DBマイグレーション | `tasks` に追加列がない旧形式DBで起動する | `prompt`、`run_at`、`notify_channel`、`source_key` が追加され既存行を保持する | MAC / LINUX |
| IT-N-036 | 廃止テーブル除去 | `preferences`、`audit_logs` を持つDBで起動する | 両テーブルが削除され、現行3テーブルが利用できる | MAC / LINUX |
| IT-N-037 | source_key冪等性 | 同一Slack投稿イベントを再処理させる | 同じ `source_key` のtaskは1件だけ存在する | MAC / LINUX |

### 5.4 Scheduler固定コマンド

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-040 | cron登録 | `schedule cron 朝の要約 \| 0 0 * * * \| 今日の予定を要約して` | active taskが作成され、`09:00 JST` を含む登録完了メッセージが返る | MAC / LINUX |
| IT-N-041 | one-shot登録 | 未来のUTC時刻で `schedule once` を送る | active taskが作成され、JST変換した時刻が表示される | MAC / LINUX |
| IT-N-042 | タスク一覧 | cronとone-shot登録後に `schedule list` | active taskだけがID・状態・JST表示付きで返る | MAC / LINUX |
| IT-N-043 | cron実行 | 直近時刻に合うcronを登録して待つ | Codex結果が `Scheduled Task` 見出し付きで通知チャンネルへ投稿され、`last_run_at` が更新される | MAC / LINUX |
| IT-N-044 | one-shot実行 | 数分後のone-shotを登録して待つ | 1回だけ実行・投稿され、taskが `done` になる | MAC / LINUX |
| IT-N-045 | 起動時復元 | 未来のtaskを登録後、実行前にアプリを再起動する | active taskが再登録され、予定時刻に実行される | MAC / LINUX |
| IT-N-046 | 期限切れone-shot整理 | 過去時刻のactive one-shotをDBに用意して起動する | 起動時に `done` へ更新され、実行されない | MAC / LINUX |
| IT-N-047 | cron更新 | `schedule update <id> \| 0 23 * * *` | SQLiteが更新され、旧handleが解除され、新cronで再登録される | MAC / LINUX |
| IT-N-048 | 削除確認要求 | `schedule delete <id>` | taskはactiveのまま、同じ会話に確認メッセージが返る | MAC / LINUX |
| IT-N-049 | 削除確定コマンド | IT-N-048後に `schedule delete confirm <id>` | taskが物理削除されず `cancelled` となり、Schedulerから解除される | MAC / LINUX |
| IT-N-050 | 削除自然文確定 | IT-N-048後に同じ会話で `はい` または `削除して` | 対象taskだけが `cancelled` になる | MAC / LINUX |
| IT-N-051 | 削除取消 | IT-N-048後に `やっぱりやめて` | pending状態が解除され、taskはactiveのまま維持される | MAC / LINUX |
| IT-N-052 | 通知投稿から会話開始 | scheduled task実行結果のスレッドへ返信する | 投稿時のsession IDを使って同じCodex文脈を継続する | MAC / LINUX |

### 5.5 自然文スケジュール

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-060 | 自然文cron登録 | `毎朝9時に今日の予定を要約して` | LLM抽出結果がconfidence 0.6以上ならcron taskとして登録される | MAC / LINUX |
| IT-N-061 | 自然文one-shot登録 | `明日の9時に資料作成を思い出させて` | UTCのone-shotとして保存され、登録結果はJST表示になる | MAC / LINUX |
| IT-N-062 | ID指定自然文更新 | `#<id>を毎朝8時に変えて` | 対象active cronだけが更新・再登録される | MAC / LINUX |
| IT-N-063 | タイトル指定自然文更新 | 一意なタイトルを指定して時刻変更を依頼する | titleまたはprompt一致が1件なら更新される | MAC / LINUX |
| IT-N-064 | ID指定自然文削除 | `#<id>を削除して` | 即時取消せず、確認メッセージを返す | MAC / LINUX |
| IT-N-065 | タイトル指定自然文削除 | 一意なタイトルを指定して削除を依頼する | 一意なactive taskを対象に確認メッセージを返す | MAC / LINUX |
| IT-N-066 | 通常会話へのfallback | スケジュールらしい語を含むが抽出confidenceが0.6未満の文を送る | taskを作らず通常のCodex会話として処理する | MAC / LINUX |

### 5.6 デフォルト自発発話

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-070 | 無効時 | `PROACTIVE_ENABLED=false` で起動する | proactive taskを作成しない | MAC / LINUX |
| IT-N-071 | 有効時の日次生成 | 有効化して起動する | 今日・明日の未来枠がone-shot taskとして作成される | MAC / LINUX |
| IT-N-072 | 投稿先fallback | `PROACTIVE_CHANNEL` を空、`SLACK_LOG_CHANNEL` を設定する | fallback先を `notify_channel` としてtaskを作る | MAC / LINUX |
| IT-N-073 | source_key重複防止 | 同じ日にアプリを複数回再起動する | `proactive:YYYY-MM-DD:n` ごとにtaskが重複しない | MAC / LINUX |
| IT-N-074 | 時間窓・最低間隔 | 生成されたtask時刻を確認する | 指定timezoneの時間窓内で、可能な場合は最低間隔を満たす | MAC / LINUX |
| IT-N-075 | proactive投稿形式 | proactive taskを実行する | `Scheduled Task` 見出しなしでCodex生成文だけを投稿する | MAC / LINUX |
| IT-N-076 | proactive投稿から会話継続 | proactive投稿のスレッドへ返信する | 投稿時のsession IDを使って会話を継続する | MAC / LINUX |
| IT-N-077 | 実行後補充 | proactive task実行完了後にDBを確認する | 実行taskが `done` になり、今日・明日の不足枠が補充される | MAC / LINUX |

### 5.7 workspaceファイル送信

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-080 | ファイル一覧 | `file list` | 非隠し通常ファイルが更新日時の新しい順、最大50件で表示される | MAC / LINUX |
| IT-N-081 | コマンド送信 | `file send report.md \| レポートです` | 現在のDMまたはスレッドへファイルとコメントが投稿される | MAC / LINUX |
| IT-N-082 | サブディレクトリ送信 | `file send images/chart.png` | 指定相対パスの画像が送信される | MAC / LINUX |
| IT-N-083 | 自然文送信 | `report.mdを送って` | 一意に解決できる場合、対象ファイルが送信される | MAC / LINUX |
| IT-N-084 | スレッド送信 | チャンネルスレッドでファイル送信を依頼する | `thread_ts` を指定して同じスレッドへアップロードされる | MAC / LINUX |
| IT-N-085 | DM送信 | DMでファイル送信を依頼する | DMへアップロードされ、不要な `thread_ts` を付けない | MAC / LINUX |
| IT-N-086 | Codexマニフェスト送信 | Codexにファイル生成と送信を依頼する | `ROBOPEN_FILE_UPLOAD` 行はSlack本文から除去され、指定ファイルが送信される | MAC / LINUX |
| IT-N-087 | 複数マニフェスト | Codexが複数の有効なマニフェスト行を返す | 本文は1回表示され、各ファイルが順番に送信される | MAC / LINUX |
| IT-N-088 | 送信ログ | ファイル送信後にDBを照会する | `[file_uploaded]`、相対パス、取得できたfile ID/permalinkがassistant messageに残る | MAC / LINUX |
| IT-N-089 | 相対file root | `SLACK_FILE_ROOT=share` とする | `CODEX_WORKSPACE_DIR/share` として解決される | MAC / LINUX |

### 5.8 Slack添付ファイル受信

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-090 | DM添付＋本文 | 小容量ファイルと指示文をDMする | UTC日付ディレクトリへ保存され、本文とファイルメタデータがCodexへ渡る | MAC / LINUX |
| IT-N-091 | 添付のみ | 本文なしで小容量ファイルをDMする | 空入力扱いにならず、添付メタデータを含むpromptでCodexが実行される | MAC / LINUX |
| IT-N-092 | 追跡済みスレッド添付 | Bot投稿または追跡済みスレッドへ添付する | 添付を保存し、同じconversation/sessionでCodexへ渡す | MAC / LINUX |
| IT-N-093 | ファイル名安全化 | `../secret report.md` 相当の名前を持つ添付を送る | パス要素が除去され、file ID付きの安全な名前で保存される | MAC / LINUX |
| IT-N-094 | 同名添付 | 同じfile ID/名前を複数回保存する | 既存ファイルを上書きせず `-2` などの連番を付ける | MAC / LINUX |
| IT-N-095 | private URL認証 | Slack private URLの添付を送る | WrapperがBot Tokenで取得し、Token自体はCodex promptやworkspaceへ記録されない | MAC / LINUX |
| IT-N-096 | inbound root外部指定 | 絶対パスの `SLACK_INBOUND_FILE_ROOT` を指定する | 指定先へ保存し、Codexには参照可能なパスが渡る | MAC / LINUX |

### 5.9 Raspberry Pi OS / systemd運用

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-N-100 | 手動起動 | SSH上で `uv run robopen-agent` | Slack DMとメンションに応答する | LINUX |
| IT-N-101 | unit登録・起動 | unitを配置し `systemctl enable --now robopen-agent` | serviceがactiveになりSocket Mode接続する | LINUX |
| IT-N-102 | SSH切断後継続 | service起動後にSSHを切断してSlackから送信する | 応答が継続する | LINUX |
| IT-N-103 | OS再起動後自動起動 | Raspberry Piを再起動する | serviceが自動起動し、既存DBとtaskを復元する | LINUX |
| IT-N-104 | 異常終了後再起動 | プロセスを強制終了する | `Restart=always` により約10秒後に再起動する | LINUX |
| IT-N-105 | journald | `journalctl -u robopen-agent -f` | 起動、Scheduler、proactive、Codexエラーを追跡できる | LINUX |
| IT-N-106 | EnvironmentFile | service経由で起動する | `.env` のSlack、Codex、DB、workspace設定が反映される | LINUX |
| IT-N-107 | SQLiteバックアップ | service稼働中に `.backup` を実行する | 整合したバックアップDBを作成できる | LINUX |
| IT-N-108 | SQLite復元 | service停止、バックアップ差替え、再起動 | conversationsとtasksが復元され、Slack疎通できる | LINUX |

## 6. 異常系・境界値テスト

### 6.1 起動・Slack・Codex異常

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-E-001 | Bot Tokenなし | `SLACK_BOT_TOKEN` を未設定で起動する | 必須環境変数不足として即時停止する | MAC / LINUX |
| IT-E-002 | App Tokenなし | `SLACK_APP_TOKEN` を未設定で起動する | Socket Mode開始前に即時停止する | MAC / LINUX |
| IT-E-003 | 無効Slack Token | 無効なtokenで起動する | 接続・認証エラーがログに残り、正常接続したように見せない | MAC / LINUX |
| IT-E-004 | 空メッセージ | 空白だけの入力を処理させる | `入力が空です` と返し、Codexを実行しない | MAC / LINUX |
| IT-E-005 | Codex実行ファイルなし | `CODEX_CMD` を存在しないパスにする | Slackへ `Codex実行でエラー` が返り、アプリ自体は継続する | MAC / LINUX |
| IT-E-006 | Codex非0終了 | Codexが非0で終了する条件を作る | exit codeとstderrを含むエラーがSlackまたはログへ出る | MAC / LINUX |
| IT-E-007 | 不正sandbox | `CODEX_SANDBOX=invalid` で会話する | 設定値エラーを返し、Codexを起動しない | MAC / LINUX |
| IT-E-008 | workspace権限なし | 書込不可workspaceで `workspace-write` を使う | 書込操作が失敗し、エラーがSlackへ返る。外部パスへ代替書込しない | MAC / LINUX |
| IT-E-009 | 危険バイパス優先 | sandboxと危険バイパスを同時に有効化する | CLIには危険バイパスだけが渡り、`--sandbox` は同時指定されない | MAC / LINUX |
| IT-E-010 | Slack API投稿失敗 | 通知先権限を外す、または無効channelを指定する | Scheduler threadは停止せず、失敗がログに記録される | MAC / LINUX |

### 6.2 SQLite異常

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-E-020 | DBパス書込不可 | 書込権限のない場所を `SQLITE_PATH` にする | 起動に失敗し、原因が明確な例外またはjournaldログに残る | MAC / LINUX |
| IT-E-021 | 破損DB | 破損したファイルをDBパスに置いて起動する | 起動失敗を検知し、破損DBを上書き・初期化しない | MAC / LINUX |
| IT-E-022 | DBロック | 外部接続で排他ロック中にメッセージ保存を発生させる | エラーを検知し、プロセス全体の無言停止や重複応答を起こさない | MAC / LINUX |
| IT-E-023 | 同時conversation作成 | 同一新規スレッドへ短時間に複数イベントを送る | UNIQUE制約違反でプロセスが落ちず、conversationが重複しない | MAC / LINUX |

### 6.3 Scheduler異常・境界値

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-E-030 | cron形式不足 | `schedule cron title \| 0 0 * * *` | 形式エラーを返しtaskを作らない | MAC / LINUX |
| IT-E-031 | 非対応cron | 分・時・曜日の範囲外、または6フィールドcronを指定する | 登録・更新を拒否しtask/handleを変更しない | MAC / LINUX |
| IT-E-032 | 不正one-shot時刻 | ISO8601でない値を登録する | 実行handleが作られないことを検知する。入力検証不足としてFAIL判定する | MAC / LINUX |
| IT-E-033 | 過去one-shot | 過去時刻で登録する | taskは次回起動時に `done` となり実行されない | MAC / LINUX |
| IT-E-034 | task ID非数値 | `schedule update abc ...`、`schedule delete abc` | 数値指定エラーを返しDBを変更しない | MAC / LINUX |
| IT-E-035 | task ID 0以下 | IDに0または負数を指定する | 1以上の指定を求め、DBを変更しない | MAC / LINUX |
| IT-E-036 | 存在しないtask更新 | 存在しないIDを更新する | active cronではない旨を返し、handleを作らない | MAC / LINUX |
| IT-E-037 | one-shot更新 | one-shot IDへcron更新を行う | 更新を拒否する | MAC / LINUX |
| IT-E-038 | cancelled/done更新 | inactive taskを更新する | 更新を拒否する | MAC / LINUX |
| IT-E-039 | 削除確認なし確定 | pendingなしで `schedule delete confirm <id>` | 削除せず、先に削除要求を送るよう返す | MAC / LINUX |
| IT-E-040 | 別会話で削除確定 | 会話Aで削除要求し、会話Bで `はい` | 対象taskを削除しない | MAC / LINUX |
| IT-E-041 | 異なるIDの確定 | task Aの確認中にtask BのIDで確定する | task A/Bとも削除しない | MAC / LINUX |
| IT-E-042 | 自然文対象なし | 存在しないタイトルを更新・削除する | 対象なしメッセージを返しDBを変更しない | MAC / LINUX |
| IT-E-043 | 自然文対象複数 | 同名taskを複数作りタイトルで更新・削除する | ID指定を促し、いずれも変更しない | MAC / LINUX |
| IT-E-044 | 自然文解析失敗 | LLMがJSON以外または不完全JSONを返す | 例外でアプリを落とさず通常会話へfallbackする | MAC / LINUX |
| IT-E-045 | 通知channelなし | scheduled taskで通知先と `SLACK_LOG_CHANNEL` を未設定にする | Codex実行と状態更新は行い、Slack投稿をスキップしてログを出す | MAC / LINUX |
| IT-E-046 | Scheduler内Codex失敗 | task実行時にCodexを失敗させる | cron threadが継続し、失敗が `[scheduler]` ログに残る | MAC / LINUX |

### 6.4 proactive異常・境界値

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-E-050 | 投稿先なし | proactive有効、両channel未設定で起動する | taskを作らず `[proactive]` ログを出す | MAC / LINUX |
| IT-E-051 | 回数0 | `PROACTIVE_TIMES_PER_DAY=0` | proactive taskを作らない | MAC / LINUX |
| IT-E-052 | 不正整数 | 回数または最低間隔に文字列を設定する | 起動時に設定エラーを検知する | MAC / LINUX |
| IT-E-053 | 不正時刻 | `PROACTIVE_WINDOW_START=xx:yy` | 起動時に設定エラーを検知する | MAC / LINUX |
| IT-E-054 | 終了時刻が開始以前 | `22:00`～`09:00` の窓を設定する | task生成時に明示的な設定エラーになる | MAC / LINUX |
| IT-E-055 | 不正timezone | 存在しないtimezone名を設定する | ZoneInfoエラーを検知し、誤ったUTC時刻で登録しない | MAC / LINUX |
| IT-E-056 | 生成Codex失敗 | proactive task実行時にCodexを失敗させる | Slack投稿せず、taskをrun済み・doneにし、ログへ記録する | MAC / LINUX |

### 6.5 ファイル送信異常・セキュリティ

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-E-060 | ファイルなし | `file send missing.txt` | 見つからない旨を返し、Slack APIを呼ばない | MAC / LINUX |
| IT-E-061 | 絶対パス | `file send /etc/passwd` | 絶対パスを拒否する | MAC / LINUX |
| IT-E-062 | パストラバーサル | `file send ../secret.txt` | 不正相対パスとして拒否する | MAC / LINUX |
| IT-E-063 | 隠しファイル | `file send .secret` または隠しディレクトリ配下 | 送信を拒否し、`file list` にも表示しない | MAC / LINUX |
| IT-E-064 | ディレクトリ | `file send images` | ディレクトリ送信を拒否する | MAC / LINUX |
| IT-E-065 | root外symlink | workspace外を指すsymlinkを指定する | root外参照として拒否する | MAC / LINUX |
| IT-E-066 | サイズ超過 | 上限超過ファイルを指定する | Slack APIを呼ばずサイズエラーを返す | MAC / LINUX |
| IT-E-067 | max bytes不正 | `SLACK_FILE_MAX_BYTES=abc` または0以下 | 設定エラーを返しファイルを送らない | MAC / LINUX |
| IT-E-068 | 自然文対象なし | 存在しないファイル名を自然文で送信依頼する | 対象なしメッセージを返す | MAC / LINUX |
| IT-E-069 | 自然文対象複数 | 同名ファイルを自然文で指定する | 候補を列挙して相対パス指定を求める | MAC / LINUX |
| IT-E-070 | Slack送信先不明 | channel情報なしでファイル送信を処理する | 送信先を特定できない旨を返す | MAC / LINUX |
| IT-E-071 | `files:write` 不足 | scopeを外して送信する | Slack APIエラーを返し、成功ログをDBへ書かない | MAC / LINUX |
| IT-E-072 | 不正マニフェストJSON | Codexが壊れたJSONを返す | Codex本文を保持して表示し、別途ファイル送信失敗を通知する | MAC / LINUX |
| IT-E-073 | マニフェストpathなし | `path` のないJSON objectを返す | ファイル送信を行わず形式エラーを通知する | MAC / LINUX |
| IT-E-074 | マニフェストroot外 | マニフェストで `../secret.txt` を指定する | Wrapperのパス検証で拒否する | MAC / LINUX |

### 6.6 Slack添付受信異常・セキュリティ

| ID | 項目 | 操作 | 期待結果 | OS |
| --- | --- | --- | --- | --- |
| IT-E-080 | Bot Tokenなし | 添付処理時にBot Tokenを利用できない状態にする | 取得失敗をSlackへ返し、Codexを実行しない | MAC / LINUX |
| IT-E-081 | URLなし | download URLを持たないfile eventを処理する | URLなしエラーを返し、空ファイルを作らない | MAC / LINUX |
| IT-E-082 | 申告サイズ超過 | Slack file objectのsizeを上限超過にする | ダウンロード前に拒否する | MAC / LINUX |
| IT-E-083 | 実サイズ超過 | 申告値は小さいが実データが上限を超える | 読込途中または取得後に拒否し、Codexへ渡さない | MAC / LINUX |
| IT-E-084 | inbound max bytes不正 | `SLACK_INBOUND_FILE_MAX_BYTES=abc` または0以下 | 設定エラーをSlackへ返し、保存しない | MAC / LINUX |
| IT-E-085 | private URL 401/403 | token権限不足または期限切れで添付を取得する | 取得失敗を通知し、Codexを実行しない | MAC / LINUX |
| IT-E-086 | 保存先権限なし | inbound rootを書込不可にする | 保存エラーを通知し、別パスへ保存しない | MAC / LINUX |
| IT-E-087 | 未追跡チャンネル添付 | 通常チャンネルの未追跡投稿に添付する | 無視し、ダウンロードしない | MAC / LINUX |

## 7. OS差分テスト

| ID | 観点 | macOS | Raspberry Pi OS / Linux | Windows |
| --- | --- | --- | --- | --- |
| IT-OS-001 | パス表現 | `/Users/...` の絶対パス、相対パス解決を確認 | `/home/...` の絶対パス、相対パス解決を確認 | `Path` 単体互換のみ。運用対象外 |
| IT-OS-002 | ファイル名・大小文字 | 通常は大小文字非区別の場合があるため、`Report.md` と `report.md` の衝突を確認 | 通常は大小文字区別。両方が別ファイルとして一覧・送信されることを確認 | 参考確認 |
| IT-OS-003 | symlink | symlink escape拒否を確認 | symlink escape拒否を確認 | 権限・作成方法が異なるため任意 |
| IT-OS-004 | ファイル権限 | workspaceとDBの読書き権限を確認 | 所有者、group、mode、systemd実行ユーザーで確認 | ACL差分は対象外 |
| IT-OS-005 | 実行ファイル探索 | `which codex`、`which uv` と `.env` の値を確認 | systemdはshellのPATHを引き継がないため絶対パスで確認 | 対象外 |
| IT-OS-006 | 環境変数読込 | shell起動と`.env`読込を確認 | `EnvironmentFile` とWorkingDirectoryからの`.env`読込を確認 | 対象外 |
| IT-OS-007 | 常駐 | foregroundまたは開発用プロセスで確認 | systemdのenable、restart、journaldを確認 | service運用対象外 |
| IT-OS-008 | timezone database | `Asia/Tokyo` のJST変換を確認 | `tzdata` 導入済みで同じ変換になることを確認 | Python環境依存のため任意 |
| IT-OS-009 | UTC日付ディレクトリ | 添付保存日がUTC基準であることを確認 | JSTの0～9時はローカル日付と異なり得ることを確認 | 任意 |
| IT-OS-010 | SQLite WAL | `agent.db-wal` / `agent.db-shm` と再起動後整合性を確認 | 同左。バックアップは `.backup` を使用する | 任意 |
| IT-OS-011 | ARM64 | Apple SiliconでCodex CLIと依存関係を確認 | Raspberry Pi ARM64でCodex CLI、Python wheel、Slack SDKを確認 | 対象外 |
| IT-OS-012 | 改行・文字コード | UTF-8、LF、Slack日本語、Markdownを確認 | UTF-8 localeと日本語ログ表示を確認 | CRLF混入時の単体互換のみ |
| IT-OS-013 | 一時ディレクトリ | `tempfile` 配下のCodex出力が実行後削除される | `/tmp` 配下が削除され、長期運用で蓄積しない | 任意 |
| IT-OS-014 | シグナル停止 | `Ctrl+C` で停止できる | `systemctl stop` で停止し、次回起動時にDBを再利用できる | 対象外 |

## 8. 回帰テスト実行順

1. `uv run pytest`
2. IT-N-001～IT-N-037で起動、Slack会話、Codex、SQLiteを確認
3. IT-N-040～IT-N-077でSchedulerとproactiveを確認
4. IT-N-080～IT-N-096で双方向ファイル連携を確認
5. IT-E系列を破棄可能なテストworkspaceとSlack Appで確認
6. ENV-LINUXでIT-N-100～IT-N-108とIT-OS系列を確認
7. DB、workspace、Slack投稿、journaldの証跡を保存し、未実装項目はN/Aとする

## 9. リリース判定基準

- `uv run pytest` が全件成功する。
- 必須環境の正常系がすべてPASSである。
- セキュリティ境界に関するIT-E-061～IT-E-066、IT-E-074、IT-E-080～IT-E-087がすべてPASSである。
- Schedulerの再起動復元、重複防止、確認付き取消がPASSである。
- Raspberry Pi本番投入時はIT-N-100～IT-N-108がすべてPASSである。
- FAILが残る場合は、影響範囲、暫定回避策、ロールバック方法を記録してから判定する。

## 10. 既知の注意点

- 固定コマンドの `schedule once` は登録時のISO8601妥当性検証が弱く、不正値でもDBへactive taskが残る可能性がある。IT-E-032で現状を明示的に確認する。
- Schedulerのcron評価はUTCで1分間隔である。秒単位の実行精度は要件外とし、最大約60秒の遅延を許容する。
- 削除確認pending状態はプロセスメモリ上にあり、確認待ち中の再起動後は復元されない。
- `CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX=true` は実装済みだが、M3のSlack承認フローではない。専用環境以外では使用しない。
- systemd常駐は手順とunit templateまで整備済みで、タスク上は実機完了待ちである。

## 11. 関連資料

- `documents/designdoc.md`
- `documents/raspberry-pi-systemd.md`
- `tasks/strategy.md`
- `tasks/01_M0_PoC_SLACK疎通.md` ～ `tasks/12_Codex危険バイパスenv対応.md`
- `tests/`
