# Project Name

## Overview

<!-- プロジェクトの概要を1-2行で記載 -->

## Tech Stack

<!-- 使用技術を記載 -->
<!-- 例: TypeScript, React, Node.js, PostgreSQL, Docker, Kubernetes -->

## Project Structure

```text
src/
├── components/    # UI コンポーネント
├── pages/         # ページ
├── services/      # API クライアント・ビジネスロジック
├── utils/         # ユーティリティ
└── types/         # 型定義
tests/
├── unit/          # ユニットテスト
├── integration/   # 統合テスト
└── e2e/           # E2E テスト（Playwright）
docs/              # ドキュメント
scripts/           # ビルド・デプロイスクリプト
.claude/
├── skills/        # カスタムスキル定義
└── agents/        # カスタムエージェント定義
```

## Conventions

- <!-- コーディング規約を記載 -->
- <!-- 命名規則を記載 -->
- テストは `tests/` 配下に配置
- コミットメッセージは Conventional Commits 形式
- Docker イメージは `Dockerfile` で定義

## Commands

```bash
npm test              # テスト実行
npm run lint          # リント
npm run build         # ビルド
docker compose up     # ローカル環境起動
make deploy-staging   # ステージングデプロイ
```

## Infrastructure

- <!-- インフラ構成を記載 -->
- `terraform plan` は許可、`terraform apply` は手動確認必須
- `kubectl delete namespace/node` は禁止

## Important Notes

- `.env.production` は読み取り禁止（settings.json の deny で制御済み）
- Agent Teams 有効 — 複数エージェントが並行作業可能
- Sandbox 有効 — Bash コマンドはサンドボックス内で実行
- Hooks でコマンドログ・ファイル変更ログを自動記録
