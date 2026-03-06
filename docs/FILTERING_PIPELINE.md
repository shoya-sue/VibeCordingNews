# 静的フィルタリングパイプライン

Gemini API 呼び出しを 0 回に抑えながら、VibeCoding/Claude Code 関連記事を自動選定する 3 段階パイプラインの設計と動作を説明します。

## 概要

```
RSS 8フィード (~58件)
  → delivered.csv 重複除去
  → [Stage 1] keyword_scorer.py   キーワード関連度スコア
  → [Stage 2] dedup_filter.py     類似タイトル重複排除
  → [Stage 3] candidate_selector.py  最終候補選定 + 静的要約生成
  → Discord配信 (Gemini API: 0回)
```

`config.json` の `static_filtering.enabled = true` 時に動作します。

---

## Stage 1: キーワードスコアリング (`scripts/keyword_scorer.py`)

### ティア別キーワード辞書

記事のタイトルと `summary_raw` を正規化（小文字化・全角→半角）してスキャンし、最高マッチティアを `static_relevance` とします。

| Tier | relevance | 代表キーワード |
|------|-----------|--------------|
| 5 | 5 | `claude code`, `vibecoding`, `バイブコーディング` |
| 4 | 4 | `claude`, `anthropic`, `mcp`, `ai agent`, `aiエージェント` |
| 3 | 3 | `copilot`, `cursor`, `llm`, `プロンプトエンジニアリング`, `cline`, `windsurf` |
| 2 | 2 | `ai`, `機械学習`, `chatgpt`, `生成ai` |
| なし | 1 | — |

> **短いキーワードの誤検知対策**: `ai`, `mcp`, `llm`, `rag` は単語境界 (`\b`) マッチを使用。
> 例: "domain" や "wait" 内の `ai` にはマッチしない。

### ソースカテゴリによる最低 relevance 保証

フィード出所が関連性を担保するカテゴリには、キーワード不一致でも下限を設けます。

| カテゴリ | 下限 | 説明 |
|---------|------|------|
| `release` | 5 | Claude Code 公式リリース |
| `official` | 5 | Anthropic 公式ニュース |
| `claude-code` | 4 | Claude Code 専用フィード |
| `vibecoding` | 4 | VibeCoding 専用フィード |
| `ai-agent` | 3 | AI エージェント専用フィード |

### composite_score の算出

```
composite_score = static_relevance × source_weight × freshness
                  [× TITLE_MATCH_BONUS=1.5 if タイトルにマッチ]
                  [+ CODE_BLOCK_BONUS=0.15 if コードブロックあり]
```

- **source_weight**: `release`/`official`=1.5, `claude-code`=1.3, `vibecoding`=1.2, その他=1.0
- **freshness**: `max(freshness_min, exp(-hours / freshness_decay_hours))` — config で調整可能

### タイトル品質フィルタ

`release`/`official` 以外のカテゴリで以下に該当する記事は除外します（バージョン番号のみタイトルは公式で正常なため除外しない）。

- タイトルが 5 文字未満
- バージョン番号のみ（例: `v2.1.69`, `2.1.69`）
- 日本語・英字を含まない

### 閾値フィルタ

`static_relevance < min_relevance`（デフォルト 3）の記事を除外。

---

## Stage 2: 類似記事重複排除 (`scripts/dedup_filter.py`)

### 文字バイグラム Jaccard 類似度

タイトルを正規化後、文字バイグラムのセットで Jaccard 類似度を算出します。

```
Jaccard(A, B) = |bigrams(A) ∩ bigrams(B)| / |bigrams(A) ∪ bigrams(B)|
```

### クラスタリング

類似度 ≥ `similarity_threshold`（デフォルト 0.4）のペアを同一クラスタとみなし、
各クラスタから `composite_score` 最高の 1 件のみ残します。

### 過去配信との類似度チェック

`delivered.csv` から読み込んだ過去タイトルと類似度 ≥ `delivered_similarity_threshold`（デフォルト 0.5）の記事を除外します。

---

## Stage 3: 最終候補選定 + 静的要約生成 (`scripts/candidate_selector.py`)

### 候補選定ルール

1. `composite_score` 降順で最大 `max_candidates`（デフォルト 5）件を選定
2. カテゴリ多様性: 同一カテゴリは最大 `max_per_category`（デフォルト 2）件
   - ただし `release`/`official` は `max_per_priority_category`（デフォルト 1）件
3. 安全弁: 候補 0 件の場合は全記事から `composite_score` 最高の 1 件を補充

### 静的要約生成

HTML タグを除去後、先頭 `summary_max_length`（デフォルト 120）文字 + `…` でトリミング。
Gemini API は不使用です。

---

## config.json パラメータ一覧

```json
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
```

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| `enabled` | `true` | パイプライン有効/無効 |
| `min_relevance` | 3 | Stage 1 閾値（1-5） |
| `similarity_threshold` | 0.4 | Stage 2 クラスタリング閾値 |
| `delivered_similarity_threshold` | 0.5 | Stage 2 過去配信との類似度閾値 |
| `max_candidates` | 5 | Stage 3 最大選定件数 |
| `max_per_category` | 2 | Stage 3 カテゴリ最大件数 |
| `max_per_priority_category` | 1 | Stage 3 公式ソース最大件数 |
| `summary_max_length` | 120 | 静的要約の最大文字数 |
| `freshness_decay_hours` | 24.0 | 鮮度が 1/e に減衰する時間（時間） |
| `freshness_min` | 0.2 | 鮮度スコアの下限値 |

---

## デバッグ: 中間結果 JSON

各ステージの出力は `data/pipeline/` に保存されます。

```
data/pipeline/
├── scored.json    # Stage 1 後（static_relevance, composite_score 付き）
├── deduped.json   # Stage 2 後（重複排除済み）
└── selected.json  # Stage 3 後（summary 付き最終候補）
```

---

## テスト

```bash
python3 -m pytest tests/test_keyword_scorer.py -v
python3 -m pytest tests/test_dedup_filter.py -v
python3 -m pytest tests/test_candidate_selector.py -v
```
