---
name: fix-issue
description: GitHub Issue を読み取り、修正コードを提案・適用する。Issue URL または番号を指定して使用。
user-invokable: true
---

# Fix Issue — GitHub Issue 修正スキル

GitHub Issue の内容を解析し、修正コードを実装するスキルです。

## いつ使うか

- 「Issue #123 を修正して」
- 「このバグを直して: [Issue URL]」
- 「Issue に書いてある機能を実装して」

## 作業手順

### Step 1: Issue 内容の取得

```bash
gh issue view [番号] --json title,body,labels,assignees,comments
gh pr list --search "closes #[番号]"
```

### Step 2: 影響範囲の調査

```bash
grep -r "[キーワード]" src/ --include="*.ts"
grep -r "[機能名]" tests/ --include="*.test.ts"
```

### Step 3: 修正実装

```bash
git checkout -b fix/issue-[番号]-[短い説明]
```

### Step 4: コミット

```bash
git add -p
git commit -m "fix: [修正内容]

Closes #[番号]

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Step 5: PR 作成

```bash
gh pr create --title "fix: [タイトル]" --body "Closes #[番号]"
```
