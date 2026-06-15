# GitHub Actionsテスト自動化

## タスクの内容

- pull requestとmainブランチへのpushで単体テストを自動実行する。
- `uv.lock` に固定された依存関係を使用し、サポート対象のPythonバージョンで互換性を確認する。
- CIにはSlack Tokenなどの運用シークレットを渡さず、モック済みのテストのみを実行する。

## ステータス

- DONE

## 成果物

- `.github/workflows/test.yml`

## 完了条件

- Python 3.11、3.12、3.13、3.14で `pytest` が実行される。
- workflowの権限がリポジトリ内容の読み取りだけに制限される。
- 同一ブランチの古い実行が新しい実行開始時にキャンセルされる。
