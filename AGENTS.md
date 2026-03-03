# Project Name

## Overview

<!-- プロジェクトの概要を1-2行で記載 -->

## Tech Stack

<!-- 使用技術を記載 -->
<!-- 例: TypeScript, React, Node.js, PostgreSQL -->

## Project Structure

```text
src/
├── components/    # UI コンポーネント
├── pages/         # ページ
├── utils/         # ユーティリティ
└── types/         # 型定義
```

## Commands

```bash
# 開発サーバー起動
npm run dev

# テスト実行
npm test

# ビルド
npm run build
```

## AI エージェント使用ポリシー（Full）

このプロジェクトでは **全機能モード** で AI エージェントを使用します。
Fleet・Plan・Agent Teams を含むすべての機能を活用します。

### ツール使い分け

| 用途 | 使用するツール |
|------|--------------|
| コードレビュー | Copilot CLI (`/code-reviewer`) / Claude Code |
| GitHub Issues 修正 | Copilot CLI (`/fix-issue #N`) |
| PR レビュー | Copilot CLI (`/review-pr #N`) |
| テスト実行・修正 | Copilot CLI (`/test-runner`) |
| コード解説 | Copilot CLI (`/explain-code`) |
| 大規模リファクタリング | Claude Code（Agent Teams 有効） |
| UI/UX 実装 | Claude Code（`/ui-ux-pro-max`） |
| ブラウザテスト | Copilot CLI（`/browser-use`） |

### Copilot CLI の動作モード

| モード | 用途 |
|--------|------|
| Interactive（デフォルト） | 対話型コーディング |
| Plan（Shift+Tab） | 実装計画の立案・確認 |
| Autopilot（実験的） | タスク完了まで自律実行 |

### Agent Teams 設定

- `teammateMode: auto` — 複雑なタスクを自動並列化
- Fleet モード（`/fleet`）— 並列サブエージェントで大規模タスクを分担

### 許可される操作

- 全ソースファイルの読み取り・編集
- `git` 全操作（force-push は要確認）
- Docker / kubectl（本番 namespace は除く）
- `terraform apply`（plan 確認後）

### 禁止される操作

- `rm -rf /`
- `kubectl delete namespace/node`
- `terraform destroy`
- 本番シークレットの読み書き
- 本番環境への無確認デプロイ

## コーディング規約

- コミットメッセージは Conventional Commits 形式（`feat:`, `fix:`, `chore:` 等）
- コメントは日本語で記述
- テストファーストで開発（TDD）
- すべてのコミットに Co-authored-by トレーラーを付与

## 注意事項

- 複雑なタスクは `/plan` で計画を立ててから実行
- Agent Teams 使用時は `/tasks` でサブエージェントの状態を確認
- セキュリティリスクがある操作は必ず人間が最終確認
