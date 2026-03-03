---
name: code-reviewer
description: コードの品質・セキュリティ・パフォーマンスをレビューする。特定ファイルや変更差分を深く分析し、重要な問題のみを報告する高 S/N 比レビュー。
user-invokable: true
---

# Code Reviewer — 高精度コードレビュースキル

ノイズを排除し、本当に重要な問題だけを報告するコードレビュースキルです。

## 指針

「$20 bill in jeans after laundry」原則 — フィードバックを見つけたとき、洗濯後のジーンズの中で $20 を発見したときのような本物の価値がなければ報告しない。

## 報告する問題 (これのみ)

1. **バグ・ロジックエラー** — 動作を壊す問題
2. **セキュリティ脆弱性** — OWASP Top 10、認証不備、機密情報露出
3. **データ損失リスク** — データが消える可能性
4. **競合状態** — 非同期処理の問題
5. **メモリリーク** — リソース解放漏れ
6. **Breaking Changes** — 公開 API の破壊的変更

## 絶対にコメントしないこと

- スタイル・フォーマット (linter に任せる)
- 命名の好み
- 「こうすればもっとよくなる」程度の提案

## 使い方

```bash
# 現在の変更をレビュー
/code-reviewer

# 特定ファイルをレビュー
@src/auth.ts /code-reviewer
```

## 出力形式

問題がある場合:
```
## Issue: [簡潔なタイトル]
**File:** path/to/file.ts:123
**Severity:** Critical | High | Medium
**Problem:** 実際のバグ・問題の明確な説明
**Suggested fix:** 修正方針
```

問題がない場合:
```
No significant issues found.
```
