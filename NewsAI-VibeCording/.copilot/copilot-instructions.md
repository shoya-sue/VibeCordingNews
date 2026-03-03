# GitHub Copilot CLI — Full 設定

## 役割と思想

このプロジェクトでは **全機能モード** で GitHub Copilot CLI を使用します。
Fleet 並列実行・Agent Teams・Skills・Agents のフル構成で開発を加速します。

## エージェント活用方針

| タスク種別 | 使用エージェント | 理由 |
|-----------|----------------|------|
| コードベース探索・質問 | `explore` (Haiku) | 高速・安価・並列安全 |
| テスト/ビルド/lint 実行 | `task` (Haiku) | 冗長出力を隔離 |
| コードレビュー | `code-review` | 専用プロンプト最適化 |
| 複雑な多段階タスク | `general-purpose` (Sonnet) | 高品質な推論が必要 |
| カスタムレビュー | `code-reviewer` agent | 高 S/N 比レビュー |
| テスト実行・修正 | `test-runner` agent | TDD サポート |
| GitHub ワークフロー | `github-workflow` agent | Issue/PR 一貫管理 |
| コード解説 | `code-explorer` agent | 日本語詳細解説 |

### Fleet モード活用

独立した並列タスクには `/fleet` を使用:
- 複数ファイルの同時リファクタリング
- 複数サービスの並列テスト実行

### Plan モード活用

複雑なタスク開始前に `Shift+Tab` で Plan モードへ切替。

## Claude Code との連携

| Copilot CLI が得意 | Claude Code が得意 |
|------------------|------------------|
| GitHub Issues/PR 操作 | 大規模リファクタリング |
| Fleet 並列エージェント | 複雑なデバッグセッション |
| MCP サーバー経由のツール | 対話的なコード設計 |
| Quick fixes & snippets | アーキテクチャ設計 |

共有コンテキスト:
- `CLAUDE.md` / `AGENTS.md` に両ツール共通の指示を記載
- プロジェクト固有の規約は `.github/copilot-instructions.md` に配置

## スキル活用ガイド

- **explain-code** — コードの構造・ロジックを日本語解説
- **code-reviewer** — コード品質・セキュリティ・パフォーマンスレビュー
- **fix-issue** — GitHub Issue を読み取り修正コードを適用
- **review-pr** — Pull Request のコードレビュー実施
- **test-runner** — テスト実行・失敗分析・修正

利用可能スキルは `/skills` コマンドで確認。

## カスタムエージェント

- `code-reviewer` — 読み取り専用・高精度レビュー
- `test-runner` — TDD サポート・失敗分析
- `github-workflow` — Issue から PR まで一貫管理
- `code-explorer` — コードベース詳細解説

## コーディング規約

- コミットメッセージは **Conventional Commits** 形式 (`feat:`, `fix:`, `chore:` 等)
- コメントは **日本語** で記述
- テストファーストで開発 (TDD)
- 最小限の変更で目的を達成する（外科的な修正）

## セキュリティ規則

- `.env.production` は読み取り禁止
- `kubectl delete namespace/node` は禁止
- `terraform apply` は手動確認必須
- シークレットをコードにコミットしない
- 本番環境への直接 push は行わない

## プロンプトのベストプラクティス (GitHub 公式)

1. **複雑なタスクは分割** — 1 プロンプト 1 タスク
2. **具体的に指定** — 入出力の例を提供
3. **コンテキストを提供** — 関連ファイルを `@` で参照
4. **フィードバックを活用** — 不満足な回答は言い換えて再試行
5. **モデルを選択** — `/model` で用途に応じたモデルを使用
6. **Copilot をガイドする** — ロールを明示して質問の精度を上げる
