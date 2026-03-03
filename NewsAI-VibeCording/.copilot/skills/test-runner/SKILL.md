---
name: test-runner
description: テストを実行し、失敗したテストの原因を分析・修正する。Jest, Vitest, pytest, cargo test, go test など主要フレームワークに対応。
user-invokable: true
---

# Test Runner — テスト実行・修正スキル

テストを実行し、失敗を分析・修正するスキルです。

## いつ使うか

- 「テストを実行して失敗を修正して」
- 「このファイルのテストを書いて」
- 「テストカバレッジを上げて」

## 手順

### Step 1: テストフレームワーク検出

```bash
cat package.json 2>/dev/null | grep -E '"test"|"jest"|"vitest"'
ls pyproject.toml pytest.ini setup.cfg 2>/dev/null
ls Cargo.toml go.mod 2>/dev/null
```

### Step 2: テスト実行

```bash
# JavaScript/TypeScript
npm test -- --passWithNoTests 2>&1 | tail -50

# Python
python -m pytest -v 2>&1 | tail -50

# Rust
cargo test 2>&1 | tail -50

# Go
go test ./... 2>&1 | tail -50
```

### Step 3: 失敗分析

1. **プロダクションコードのバグ** → プロダクションコードを修正
2. **テストコードのバグ** → テストを修正（仕様変更追従）
3. **環境・依存関係問題** → 設定確認
4. **フレイキーテスト** → 非決定性の原因を調査・報告

## テスト記述 (TDD)

```typescript
// AAA パターン
it('should [期待する動作]', () => {
  // Arrange
  const input = setupTestData();
  // Act
  const result = functionUnderTest(input);
  // Assert
  expect(result).toBe(expected);
});
```
