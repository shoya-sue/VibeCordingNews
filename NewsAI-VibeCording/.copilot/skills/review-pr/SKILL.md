---
name: review-pr
description: Pull Request のコードレビューを実施する。PR の差分を解析し、バグ・セキュリティ・パフォーマンス問題を指摘。
user-invokable: true
---

# Review PR — Pull Request レビュースキル

Pull Request を徹底レビューするスキルです。

## いつ使うか

- 「この PR をレビューして: [URL]」
- 「現在のブランチの変更をレビューして」
- 「PR #42 のセキュリティ観点でチェックして」

## レビュー手順

### Step 1: 変更内容の把握

```bash
gh pr view [番号] --json title,body,files,reviews,comments
gh pr diff [番号]
# または現在のブランチ
git diff main...HEAD
```

### Step 2: コードレビュー観点

1. **バグ・ロジックエラー** — 動作を壊す問題
2. **セキュリティ脆弱性** — 入力検証、認証、XSS/SQL インジェクション
3. **パフォーマンス** — N+1 クエリ、メモリリーク、不要な再レンダリング
4. **テストカバレッジ** — 重要なパスがカバーされているか
5. **Breaking Changes** — 公開 API の破壊的変更

### Step 3: レビューコメント投稿

```bash
gh pr review [番号] --comment -b "[コメント]"
gh pr review [番号] --request-changes -b "[コメント]"
gh pr review [番号] --approve
```

## 出力形式

```markdown
## PR レビュー: #[番号]

### 🔴 要対応
- [重要な問題]

### 🟡 確認推奨
- [注意点]

### ✅ 良い点
- [良い実装]

**判定**: Approve / Request Changes / Comment
```
