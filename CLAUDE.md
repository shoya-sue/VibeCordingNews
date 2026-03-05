# NewsAI-VibeCording

## Overview

Claude Code / VibeCoding 関連ニュースを自動収集し、Discord に定時配信する無料ニュースBot。
AI API呼び出し0回の3段階静的フィルタリングパイプラインで記事を厳選する。

## Tech Stack

- Python 3.12（配信・フィルタリング・知識抽出）
- GitHub Actions（定時実行: JST 10:00 / 15:00）
- Cloudflare Workers + Node.js（対話Bot常駐）
- Gemini API Flash-Lite（知識抽出・RAG用、配信フィルタには不使用）
- Discord Webhook（記事配信）

## Project Structure

```text
scripts/
├── fetch_and_deliver.py   # 配信エントリポイント（RSS取得→フィルタ→Discord配信）
├── keyword_scorer.py      # Stage 1: ティア別キーワードスコアリング
├── dedup_filter.py        # Stage 2: 文字バイグラムJaccard重複排除
├── candidate_selector.py  # Stage 3: 最終候補選定 + 静的要約生成
├── extract_knowledge.py   # Gemini APIで知識抽出 → knowledge_base
├── memory_manager.py      # 忘却曲線による保持率管理
└── requirements.txt       # feedparser, requests
tests/
├── test_keyword_scorer.py
├── test_dedup_filter.py
├── test_candidate_selector.py
└── __init__.py
data/
├── delivered.csv          # 配信済みURL・スコア管理
├── processed_ids.json     # RAG処理済みID
├── pipeline/              # 各ステージの中間結果JSON
├── knowledge_base/        # BM25知識DB（entries.jsonl）
└── episodic_memory/       # 忘却曲線データ
worker/                    # Cloudflare Worker（対話Bot）
├── src/index.js
└── wrangler.toml
.github/workflows/
├── news-delivery.yml      # 定時配信（JST 10:00/15:00）
├── extract-knowledge.yml  # 知識抽出（JST 21:00）
└── deploy-worker.yml      # Worker手動デプロイ
config.json                # RSSフィード設定 & フィルタリングパラメータ
```

## Conventions

- コメントは日本語で記述
- Python: スネークケース（変数・関数）
- テストは `tests/` 配下に配置（pytest）
- コミットメッセージは Conventional Commits 形式（`feat:`, `fix:`, `docs:` 等）
- 配信パイプラインの中間結果は `data/pipeline/` にJSON保存

## Commands

```bash
python3 -m pytest tests/ -v                    # ユニットテスト実行
python3 scripts/fetch_and_deliver.py           # ローカル配信実行（要環境変数）
python3 scripts/extract_knowledge.py           # 知識抽出（要GEMINI_API_KEY）
```

## Infrastructure

- GitHub Actions: 月間約210分消費（無料枠2,000分の10%）
- Gemini API: 無料枠内（1,000回/日）
- Cloudflare Workers: 無料枠内（10万リクエスト/日）
- 合計コスト: $0

## Important Notes

- `.env.production` は読み取り禁止（settings.json の deny で制御済み）
- Agent Teams 有効 — 複数エージェントが並行作業可能
- Sandbox 有効 — Bash コマンドはサンドボックス内で実行
- Hooks でコマンドログ・ファイル変更ログを自動記録
- `static_filtering.enabled=true` 時はGemini API呼び出し0回で配信可能
- RSSフィード: Zenn(4), Qiita(2), GitHub Releases(1), Anthropic News(1) の計8フィード
