# diary

## 目的

`robopen-agent-py/data/agent.db` に保存された ryopen との作業ログを読み取り、今日の出来事を `diary/{yyyymmdd}.md` へ日記として記録するペン。

## 使うタイミング

ryopen が `/diary`、`日記を書いて`、`今日の日記を書いて`、`作業ログから日記`、`今日の出来事を記録して` と依頼したときに使うペン。

## 入力

- 作業ログDB: `../data/agent.db` ペン。
- 出力先: `diary/{yyyymmdd}.md` ペン。
- 日付: 指定がなければ現在のローカル日付を使うペン。
- タイムゾーン: ワークスペースの `timezone` を優先し、通常は `Asia/Tokyo` として扱うペン。

## 手順

1. `date +%Y%m%d` で対象日の日記ファイル名を決めるペン。
2. `../data/agent.db` が存在するか確認するペン。
3. DBスキーマを確認し、少なくとも `conversations`、`messages`、`tasks` があることを確認するペン。
4. 対象日のローカル日付範囲で、`messages.created_at`、`conversations.started_at`、`tasks.run_at`、`tasks.last_run_at` を読むペン。SQLite で読む場合は UTC の保存時刻に `+9 hours` を足して JST 日付として扱うペン。
5. 次の観点で今日の出来事を短く整理するペン。
   - ryopen から依頼されたことペン。
   - robopen が返答・実行したことペン。
   - 作成・更新したファイルやスキルペン。
   - 予約タスクや実行済みタスクの結果ペン。
   - 次回以降に覚えておくとよい未完了事項ペン。
6. シークレット、トークン、鍵、認証情報、個人情報の詳細は日記に書かないペン。必要なら「認証情報を扱う作業があった」程度にぼかすペン。
7. `diary/{yyyymmdd}.md` がなければ `# {yyyymmdd}` の見出しで作るペン。既にある場合は既存内容を読んで、重複しない内容だけ追記するペン。
8. 日記は箇条書きで簡潔に書くペン。各項目は、後から読み返して状況が分かる粒度にするペン。
9. 必要に応じて、今後3ヶ月ほど覚えておくべき近況やワークスペース情報だけ `MEMORY.md` へ移すか判断するペン。判断に迷う場合は `MEMORY.md` は更新しないペン。
10. 書き込み後にファイルを読み返し、日付、重複、秘密情報混入がないことを確認するペン。

## 参考コマンド

対象日のログ確認例ペン。

```sh
sqlite3 -header -column ../data/agent.db "
select m.id, m.conversation_id, m.role, m.created_at,
       substr(replace(m.content, char(10), ' '), 1, 240) as content
from messages m
where date(m.created_at, '+9 hours') = 'YYYY-MM-DD'
order by m.created_at;
"
```

タスク確認例ペン。

```sh
sqlite3 -header -column ../data/agent.db "
select id, title, status, run_at, last_run_at, notify_channel, source_key
from tasks
where date(run_at, '+9 hours') = 'YYYY-MM-DD'
   or date(last_run_at, '+9 hours') = 'YYYY-MM-DD'
order by coalesce(last_run_at, run_at, '');
"
```

## 出力

- `diary/{yyyymmdd}.md` を作成または更新するペン。
- 必要な場合だけ `MEMORY.md` を更新するペン。
- ryopen には、更新したファイルと主な追記内容を短く伝えるペン。

## 注意

- DBのログは作業材料であり、そのまま全文転載しないペン。
- SlackのメンションID、チャンネルID、thread_ts は必要がなければ日記に書かないペン。
- 日記は事実ベースにし、推測は「たぶん」「未確認」と分かる形で書くペン。
- 削除や外部送信は行わないペン。
