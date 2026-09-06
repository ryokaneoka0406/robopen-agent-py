# Dependabot導入

## タスクの内容

- uvで管理するPython依存関係とGitHub Actionsの更新をDependabotで検出する。
- 定期更新のpull request数を抑えつつ、major更新は個別にレビューできる構成にする。

## ステータス

- DONE

## 成果物

- `.github/dependabot.yml`
- `documents/designdoc.md`

## 完了条件

- `uv` と `github-actions` の2 ecosystemを週次で確認する。
- minor/patch更新はecosystemごとに1つのpull requestへまとめる。
- major更新は個別pull requestとして作成する。
- 同時に開くversion updateのpull requestをecosystemごとに最大5件へ制限する。
