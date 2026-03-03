---
name: fix-issue
description: GitHub Issue を読み取り、修正コードを提案・適用する
argument-hint: "<issue-number>"
user-invokable: true
---

# fix-issue

GitHub Issue `$ARGUMENTS` の内容を確認し、修正を行ってください。

## 手順

1. `gh issue view $ARGUMENTS` で Issue の内容を確認
2. 関連するコードを特定
3. 原因を分析
4. 修正コードを書く
5. テストを実行して修正を確認
6. 変更内容のサマリーを出力
