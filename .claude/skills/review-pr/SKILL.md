---
name: review-pr
description: Pull Request のコードレビューを実施する
argument-hint: "<pr-number>"
user-invokable: true
---

# review-pr

Pull Request `$ARGUMENTS` のコードレビューを行ってください。

## レビュー観点

1. **正しさ** — ロジックにバグがないか
2. **セキュリティ** — インジェクション、認証漏れ等の脆弱性
3. **パフォーマンス** — N+1 クエリ、不要な再レンダリング等
4. **可読性** — 命名、構造、コメントの適切さ
5. **テスト** — テストカバレッジ、エッジケース

## 出力形式

各指摘を以下の形式で出力:

- **[重要度: High/Medium/Low]** ファイル名:行番号 — 指摘内容
