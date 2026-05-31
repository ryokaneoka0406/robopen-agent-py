# WorkspaceファイルSlack送信

## 目的

- `workspace/share/` 配下のMarkdownや画像などをSlackへアップロードできるようにする。
- Slack Bot TokenはWrapper側だけで保持し、Codex CLIには渡さない。

## 実装内容

- `SLACK_FILE_ROOT` 未設定時は `CODEX_WORKSPACE_DIR/share` を送信対象rootにする。
- `SLACK_FILE_MAX_BYTES` 未設定時は20MBを上限にする。
- `file list` / `file send <relative_path> | <comment>` をSlack入力として受け付ける。
- `report.mdを送って` などの自然文から一意に解決できるファイルを送信する。
- Codex応答末尾の `ROBOPEN_FILE_UPLOAD {"path":"...","comment":"..."}` を検出し、マニフェスト行をSlack表示から除いたうえで自動送信する。
- root外参照、絶対パス、`../`、root外symlink、隠しファイル、ディレクトリ、サイズ超過を拒否する。
- 成功時はSQLite `messages` に `[file_uploaded] <relative_path>` を保存する。

## 完了条件

- `workspace/share/report.md` をSlack DMまたはスレッドへ送信できる。
- `workspace/share/images/chart.png` を自然文で送信できる。
- Codexが `ROBOPEN_FILE_UPLOAD` マニフェストを返した場合、確認なしでSlackへアップロードされる。
- 不正パスとサイズ超過は送信されず、Slackへエラーメッセージが返る。
- 既存の通常会話、スケジューラ、proactive投稿のテストが通る。
