# 📰 NewsAI-VibeCording

VibeCoding / Claude Code / AI Coding 関連のニュースを自動収集し、Discord に配信する無料ニュースBot。

## ✨ 機能

### 🔔 定時配信（Push型）
- **10:00 / 15:00 JST** に最新ニュース5件を自動配信
- GitHub Actions cron による定期実行
- **静的フィルタリングパイプライン**でAI API呼び出し0回の記事厳選
- 配信済み記事は CSV 管理で再配信防止

### 💬 対話Bot（Pull型）
- `/news` — 最新ニュースを即座に取得
- `/ask <質問>` — VibeCoding関連の質問にAIが回答
- `/status` — Botの稼働状況を確認
- Cloudflare Workers で常駐サーバー不要

## 📡 情報ソース

| ソース | カテゴリ |
|---|---|
| Zenn - Claude Code | 技術記事 |
| Zenn - Claude | 技術記事 |
| Zenn - VibeCoding | 技術記事 |
| Zenn - AI Agent | 技術記事 |
| Qiita - ClaudeCode | 技術記事 |
| Qiita - バイブコーディング | 技術記事 |
| Claude Code GitHub Releases | リリース情報 |
| Anthropic News | 公式発表 |

## 🏗️ アーキテクチャ

```
┌──────────────────────────────────────────────────────────┐
│           NewsAI-VibeCording Architecture                │
│                                                          │
│  【配信フロー】 1日2回 (JST 10:00 / 15:00)               │
│  ┌─────────────┐     ┌──────────────────────┐            │
│  │ GitHub      │cron │ fetch_and_deliver.py  │            │
│  │ Actions     │────▶│  ├─ feedparser (RSS) │            │
│  │ news-       │     │  ├─ 静的フィルタリング│            │
│  │ delivery    │     │  └─ Webhook POST     │            │
│  └─────────────┘     └──────────┬───────────┘            │
│                                 │ Discord配信             │
│                                 ▼                        │
│                      ┌──────────────────┐   ┌──────────┐ │
│                      │   Discord        │◀──│Cloudflare│ │
│                      │   Channel        │   │ Worker   │ │
│                      └──────────────────┘   └──────────┘ │
│                                 │ delivered.csv 更新      │
│                                 ▼                        │
│                      ┌──────────────────────┐            │
│                      │  data/delivered.csv  │            │
│                      │  (配信済みURL管理)    │            │
│                      └──────────────────────┘            │
│                                                          │
│  【知識蓄積フロー】 1日1回 (JST 10:30)                   │
│  ┌─────────────┐     ┌──────────────────────┐            │
│  │ GitHub      │cron │ extract_knowledge.py  │            │
│  │ Actions     │────▶│  ├─ 未処理記事を取得  │            │
│  │ extract-    │     │  ├─ Gemini API (抽出) │            │
│  │ knowledge   │     │  └─ BM25インデックス  │            │
│  └─────────────┘     └──────────┬───────────┘            │
│                                 │                        │
│                                 ▼                        │
│                      ┌──────────────────────┐            │
│                      │ data/knowledge_base/ │            │
│                      │  ├─ entries.jsonl    │ ← 知識DB   │
│                      │  └─ bm25_index.pkl   │ ← 検索用  │
│                      └──────────────────────┘            │
│                                 │                        │
│                                 ▼                        │
│                      ┌──────────────────────┐            │
│                      │ memory_manager.py     │            │
│                      │  └─ 忘却曲線で保持率  │            │
│                      │     を毎日更新        │            │
│                      └──────────────────────┘            │
└──────────────────────────────────────────────────────────┘
```

### 📊 静的フィルタリングパイプライン（配信フロー詳細）

Gemini API のレート制限 (429) を回避するため、記事の厳選と要約をすべてローカル処理で完結させる設計。
AI API 呼び出し **0回** で配信候補を選定する。

```
RSS 8フィード (~80エントリ)
  │
  ▼
delivered.csv URL重複除去          ← 既知URLを除外
  │  (~50-60件)
  ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 1: keyword_scorer.py — キーワード関連度スコアリング│
│                                                          │
│  ティア別キーワード辞書で static_relevance (1-5) を判定   │
│                                                          │
│  Tier 1 (=5): claude code, vibecoding, バイブコーディング│
│  Tier 2 (=4): claude, anthropic, MCP, ai agent           │
│  Tier 3 (=3): copilot, cursor, LLM, プロンプトエンジニアリング│
│  Tier 4 (=2): AI, 機械学習, chatgpt, 生成AI   ← 除外    │
│  マッチなし (=1):                              ← 除外    │
│                                                          │
│  composite_score = relevance × ソース重み × 鮮度          │
│    ソース重み: release/official=1.5, claude-code=1.3      │
│    鮮度: max(0.2, exp(-hours/24))                        │
│    タイトルマッチ: ×1.5 ボーナス                          │
└──────────┬──────────────────────────────────────────────┘
           │  relevance ≥ 3 のみ通過 (~15-20件)
           ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 2: dedup_filter.py — 類似タイトル重複排除          │
│                                                          │
│  文字バイグラム Jaccard 類似度で判定                       │
│    記事間: ≥ 0.4 → 同一クラスタ → 最高スコアの1件を残す  │
│    過去配信: ≥ 0.5 → 除外                                │
└──────────┬──────────────────────────────────────────────┘
           │  (~10-15件)
           ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 3: candidate_selector.py — 最終選定 + 静的要約     │
│                                                          │
│  composite_score 上位から最大5件を選定                     │
│    カテゴリ多様性: 同一カテゴリ最大2件                     │
│    安全弁: 候補0件時は最高スコア1件を補充                  │
│                                                          │
│  要約: summary_raw → HTMLタグ除去 → 先頭120文字 + "…"     │
└──────────┬──────────────────────────────────────────────┘
           │  3-5件（summary付き）
           ▼
      Discord Webhook 配信
```

> **Gemini API の残る役割**: 知識蓄積フロー (`extract_knowledge.py`) でのみ使用。
> 配信フローでは `static_filtering.enabled=true`（デフォルト）の間 API 呼び出しは発生しない。
> `config.json` で `static_filtering.enabled=false` に設定すると従来の Gemini 要約フローにフォールバック可能。

## ⚙️ GitHub Actions ワークフロー

2つのワークフローに分離することで、無料枠（2,000分/月）を効率的に使用しています。

### 📰 news-delivery.yml — 配信専用

| 項目 | 内容 |
|---|---|
| 実行タイミング | JST 10:00 / 15:00（1日2回） |
| 処理内容 | RSS収集 → 静的フィルタリング（3段階） → Discord Webhook配信 |
| 所要時間 | 約1〜2分/回（API呼び出しなし） |
| 月間消費 | 約60分 |

### 🧠 extract-knowledge.yml — 知識蓄積専用

| 項目 | 内容 |
|---|---|
| 実行タイミング | JST 10:30（1日1回、配信の30分後） |
| 処理内容 | 未処理記事をGeminiで解析 → knowledge_base に蓄積 → 忘却曲線で保持率更新 |
| 所要時間 | 約3〜5分/回 |
| 月間消費 | 約150分 |

**月間合計: 約210分**（無料枠2,000分の10%）

### 知識の蓄積ロジック

```
実行のたびに:
  delivered.csv の未処理URL を取得
       ↓
  processed_ids.json で処理済みかチェック
       ↓ 未処理のみ
  Gemini API で知識を抽出（最大20件/回）
  ※ 429レート制限エラー時 → 90秒待機後1回リトライ
  ※ リトライも失敗 → processed_ids に記録せず次回へ持ち越し
       ↓ 成功のみ
  data/knowledge_base/entries.jsonl に追記
  data/processed_ids.json に記録（次回スキップ）
       ↓
  memory_manager.py で忘却曲線計算（保持率更新）
```

これにより日々記事が蓄積され、`/ask` スラッシュコマンドで使うBM25検索の精度が向上していきます。

## 💰 コスト

| サービス | 費用 |
|---|---|
| GitHub Actions | **無料** (Public repo) |
| Gemini API (Flash-Lite) | **無料** (1,000回/日) |
| Cloudflare Workers | **無料** (10万リクエスト/日) |
| Discord Bot | **無料** |
| **合計** | **$0** |

## 🚀 セットアップ

### 1. 事前準備

以下のアカウント/トークンが必要です:

| 項目 | 取得先 |
|---|---|
| Discord Webhook URL | サーバー設定 → 連携サービス → ウェブフック |
| Discord Application | https://discord.com/developers/applications |
| Gemini API Key | https://aistudio.google.com/apikey |
| Cloudflare Account | https://dash.cloudflare.com/ |

### 2. リポジトリの準備

```bash
git clone https://github.com/<your-username>/NewsAI-VibeCording.git
cd NewsAI-VibeCording
```

### 3. GitHub Secrets の設定

リポジトリの Settings → Secrets and variables → Actions に以下を追加:

| Secret名 | 値 |
|---|---|
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL |
| `GEMINI_API_KEY` | Gemini API キー |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API トークン |

### 4. Discord Bot のセットアップ

```bash
# Discord Developer Portal でアプリケーションを作成
# Bot Token と Application ID を取得

cd worker
npm install

# Slash Commands の登録
DISCORD_APPLICATION_ID=<your-app-id> \
DISCORD_BOT_TOKEN=<your-bot-token> \
node src/register-commands.js
```

### 5. Cloudflare Worker のデプロイ

```bash
cd worker
npm install

# Secrets を設定
npx wrangler secret put DISCORD_PUBLIC_KEY
npx wrangler secret put GEMINI_API_KEY

# デプロイ
npx wrangler deploy
```

デプロイ後に表示される Worker URL を Discord Developer Portal の
**Interactions Endpoint URL** に設定してください。

### 6. 手動テスト

```bash
# 定時配信を手動実行
DISCORD_WEBHOOK_URL=<url> GEMINI_API_KEY=<key> python scripts/fetch_and_deliver.py

# または GitHub Actions の workflow_dispatch から実行
```

## 📁 ディレクトリ構成

```
NewsAI-VibeCording/
├── .github/
│   └── workflows/
│       ├── news-delivery.yml    # 定時配信（JST 10:00/15:00）
│       ├── extract-knowledge.yml # 知識蓄積（JST 10:30、1日1回）
│       └── deploy-worker.yml    # Worker手動デプロイ
├── worker/
│   ├── src/
│   │   ├── index.js             # Cloudflare Worker メインロジック
│   │   └── register-commands.js # Slash Command 登録スクリプト
│   ├── wrangler.toml
│   └── package.json
├── scripts/
│   ├── fetch_and_deliver.py     # RSS収集 & Discord配信（メインエントリ）
│   ├── keyword_scorer.py        # Stage 1: キーワード関連度スコアリング
│   ├── dedup_filter.py          # Stage 2: 類似タイトル重複排除
│   ├── candidate_selector.py    # Stage 3: 最終候補選定 + 静的要約
│   ├── config_validator.py      # config.json スキーマバリデーター
│   ├── extract_knowledge.py     # Gemini APIで知識抽出 & RAG構築
│   ├── memory_manager.py        # 忘却曲線による保持率管理
│   └── requirements.txt
├── tests/
│   ├── test_keyword_scorer.py   # Stage 1 ユニットテスト
│   ├── test_dedup_filter.py     # Stage 2 ユニットテスト
│   ├── test_candidate_selector.py # Stage 3 ユニットテスト
│   ├── test_fetch_and_deliver.py  # 配信エントリポイント ユニットテスト
│   ├── test_config_validator.py   # バリデーター ユニットテスト
│   └── __init__.py
├── docs/
│   └── FILTERING_PIPELINE.md    # 静的フィルタリングパイプライン設計ドキュメント
├── data/
│   ├── delivered.csv            # 配信済み記事DB
│   ├── pipeline/                # フィルタリング中間結果（デバッグ用）
│   │   ├── scored.json          # Stage 1 出力
│   │   ├── deduped.json         # Stage 2 出力
│   │   └── selected.json        # Stage 3 出力
│   ├── processed_ids.json       # RAG処理済み記事ID
│   ├── knowledge_base/          # 抽出済み知識（蓄積データ）
│   │   ├── entries.jsonl        # 知識エントリ
│   │   └── bm25_index.pkl       # BM25検索インデックス
│   └── episodic_memory/         # エピソード記憶（忘却曲線データ）
├── config.json                  # フィード設定 & レート制限
├── .gitignore
└── README.md
```

## ⚙️ カスタマイズ

### フィードの追加

`config.json` の `feeds` 配列に新しいエントリを追加:

```json
{
  "name": "表示名",
  "url": "https://example.com/feed",
  "category": "カテゴリ名",
  "lang": "ja",
  "emoji": "🆕"
}
```

### 静的フィルタリングの調整

`config.json` の `static_filtering` で設定:

```json
{
  "static_filtering": {
    "enabled": true,
    "min_relevance": 3,
    "similarity_threshold": 0.4,
    "delivered_similarity_threshold": 0.5,
    "max_candidates": 5,
    "max_per_category": 2,
    "max_per_priority_category": 1,
    "summary_max_length": 120,
    "freshness_decay_hours": 24.0,
    "freshness_min": 0.2
  }
}
```

| パラメータ | 説明 | デフォルト |
|---|---|---|
| `enabled` | `true` で静的パイプライン、`false` で従来Geminiフロー | `true` |
| `min_relevance` | この値未満のキーワードティアを除外 | `3` |
| `similarity_threshold` | 記事間のJaccard類似度閾値（重複判定） | `0.4` |
| `delivered_similarity_threshold` | 過去配信との類似度閾値 | `0.5` |
| `max_candidates` | 最終配信候補の上限数 | `5` |
| `max_per_category` | 同一カテゴリの最大件数 | `2` |
| `max_per_priority_category` | `release`/`official` カテゴリの最大件数 | `1` |
| `summary_max_length` | 静的要約の最大文字数 | `120` |
| `freshness_decay_hours` | 鮮度スコアが 1/e に減衰するまでの時間（時間） | `24.0` |
| `freshness_min` | 鮮度スコアの下限値（古い記事でも最低限のスコアを保証） | `0.2` |

### レート制限の調整（従来フロー用）

`config.json` の `rate_limits` で設定（`static_filtering.enabled=false` 時のみ使用）:

```json
{
  "gemini_daily_max": 50,
  "discord_interactions_per_hour": 30
}
```

## 📚 ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/FILTERING_PIPELINE.md](docs/FILTERING_PIPELINE.md) | 静的フィルタリングパイプラインの詳細設計（各ステージのアルゴリズム・パラメータ説明） |

## 📄 License

MIT
