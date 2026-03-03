# VibeちゃんBot — 記憶アーキテクチャ設計書

> **作成日**: 2026-03-03
> **対象**: Claude Code 実装引き継ぎ
> **ステータス**: 設計確定 / 実装待ち
> **参照論文**: [MemoryBank (AAAI2024)](https://arxiv.org/abs/2305.10250) / [Memoria (2024)](https://arxiv.org/abs/2512.12686)

---

## 0. 構想の理解と整理

ユーザーの構想を認知科学の用語に対応させると以下になります。

| ユーザーの表現 | 認知科学の概念 | 実装上の名前 |
|--------------|--------------|-------------|
| 会話履歴テーブル | エピソード記憶 | `ConversationStore` |
| 思い出しした履歴を係数として持つ | 記憶強度 / 忘却曲線 | `memory_strength` (S値) |
| 繰り返すと思い出ししやすい | 間隔反復効果（エビングハウス） | `recall_count` × `half_life` |
| 体に刻まれた知識 | 意味記憶・手続き記憶への統合 | `PersonalityMemory` |
| 人格に近い部分に蓄積 | 記憶の固定化（consolidation） | `character_knowledge` |

**一言で言うと**: 人間の記憶と全く同じ3層構造 + 忘却曲線を実装します。

---

## 1. 全体アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────┐
│                    VibeちゃんBot 記憶システム                     │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  Layer 1         │  │  Layer 2         │  │  Layer 3     │  │
│  │  作業記憶         │  │  エピソード記憶    │  │  意味記憶    │  │
│  │ (Working Memory) │  │ (Episodic Memory) │  │(Semantic)    │  │
│  │                  │  │                  │  │              │  │
│  │  今の会話3〜5ターン │  │  過去の会話ログ    │  │  体に刻まれた │  │
│  │  コンテキストウィンドウ│  │  忘却曲線で管理   │  │  人格知識     │  │
│  │                  │  │  recall_count    │  │ character_   │  │
│  │  揮発（会話終了で消）│  │  memory_strength │  │ knowledge[]  │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
│           │                      │                    │         │
│           ▼                      ▼                    ▼         │
│      Cloudflare KV         Cloudflare KV        GitHub JSON     │
│      (セッション)          (ユーザー別)          (永続・全体共有)  │
└─────────────────────────────────────────────────────────────────┘
```

### データフロー（1回の /ask コマンド）

```
ユーザー発言
    │
    ▼
① 感情計算 (computeEmotionState) ← 既存v2.1
    │
    ▼
② 記憶検索（3層から並列取得）
    ├─ Layer1: 直近3ターンをそのまま
    ├─ Layer2: エピソード記憶から関連エントリを想起（strength更新）
    └─ Layer3: 人格知識から関連ナレッジを注入
    │
    ▼
③ プロンプト構築
    │  [システムプロンプト(Big Five + フェーズ + 感情)]
    │  [想起された記憶セクション]
    │  [人格知識セクション]
    │  [会話履歴3ターン]
    │
    ▼
④ Gemini API (dynamicTemp)
    │
    ▼
⑤ 応答後の記憶更新
    ├─ 会話をLayer2に追記（新エントリ, strength=1, count=0）
    ├─ 想起したエントリのstrengthを+1（忘却曲線リセット）
    └─ 高価値エントリをLayer3への昇格候補にマーク
```

---

## 2. Layer 1 — 作業記憶（Working Memory）

### 概要
既存の `emotionSessionStore` に `history` を追加するだけで実現できます。**最小工数・最大効果**の実装です。

### データ構造（KV保存）

```javascript
// Cloudflare KV key: `session:{userId}`
{
  "state": {                         // 感情状態（既存）
    "tension": 82,
    "curiosity": 95,
    "confidence": 67,
    "empathy": 66,
    "fatigue": 10
  },
  "lastResponseEnding": "だよ！",    // 禁止語尾（既存）
  "history": [                       // ★ 追加: 直近3〜5ターン
    { "role": "user",  "parts": [{ "text": "Claude Codeの使い方は？" }] },
    { "role": "model", "parts": [{ "text": "えっとね！Claude Code..." }] },
    { "role": "user",  "parts": [{ "text": "MCPって何？" }] },
    { "role": "model", "parts": [{ "text": "MCP（Model Context Protocol）はね..." }] }
  ],
  "updated_at": "2026-03-03T10:30:00Z"
}
```

### 実装変更点（index.js）

```javascript
// askGemini() 内
const session = JSON.parse(await env.SESSION_KV.get(`session:${userId}`) || "null")
  || { state: {...DEFAULT_EMOTION}, lastResponseEnding: null, history: [] };

// Gemini API の contents を履歴込みに変更
const contents = [
  ...session.history.slice(-6),  // 直近3往復 = 6メッセージ
  { role: "user", parts: [{ text: userMessage }] }
];

// 応答後の保存
await env.SESSION_KV.put(`session:${userId}`, JSON.stringify({
  state: newState,
  lastResponseEnding: extractLastEnding(responseText),
  history: [
    ...session.history.slice(-8),   // 最大4往復を保持
    { role: "user",  parts: [{ text: userMessage }] },
    { role: "model", parts: [{ text: responseText }] },
  ],
  updated_at: new Date().toISOString(),
}), { expirationTtl: 86400 });  // 24時間で自動削除
```

---

## 3. Layer 2 — エピソード記憶（Episodic Memory + 忘却曲線）

### 概要

**MemoryBank論文**のアルゴリズムを採用します。エビングハウス忘却曲線 `R = e^(-t/S)` をベースに、想起するたびに記憶強度 S が増加して「忘れにくく」なります。

### 忘却曲線モデル

```
記憶保持率 R = e^(-t/S)

t = 最後に想起されてからの経過時間（時間単位）
S = 記憶強度（初期値=1、想起されるたびに+1）

recall_count = 0: S=1 → 24時間後 R=0.37（急速に薄れる）
recall_count = 1: S=2 → 24時間後 R=0.61（少し定着）
recall_count = 3: S=4 → 24時間後 R=0.78（かなり定着）
recall_count = 7: S=8 → 24時間後 R=0.88（長期記憶化）

→ 繰り返し「思い出される」ほど、記憶が強化されていく
```

### データ構造

```javascript
// Cloudflare KV key: `episodic:{userId}:{YYYYMM}`
// または GitHub: data/memory/{userId}/episodic_YYYYMM.json
{
  "entries": [
    {
      "id": "ep_20260303_001",
      "type": "conversation",          // conversation / article / insight
      "created_at": "2026-03-03T10:00:00Z",
      "last_recalled_at": "2026-03-03T14:00:00Z",
      "recall_count": 3,               // 想起回数（増えるほど忘れにくい）
      "memory_strength": 4,            // S値（recall_count + 1）
      "retention_score": 0.78,         // 現在の保持率（計算値）
      "keywords": ["claude", "mcp", "tool-use"],
      "summary": "ユーザーがMCPとTool Useの違いを質問。MCPは外部システム連携、Tool UseはGeminiのfunction callingに相当すると説明した。",
      "emotional_context": {           // その時の感情状態（雰囲気の記憶）
        "tension": 85,
        "curiosity": 95
      }
    }
  ]
}
```

### 記憶強度の計算ロジック

```python
# scripts/memory_manager.py （新規作成予定）
import math
from datetime import datetime, timezone

def compute_retention(entry: dict) -> float:
    """現在の記憶保持率を計算（0.0〜1.0）"""
    last_recalled = datetime.fromisoformat(entry["last_recalled_at"])
    now = datetime.now(timezone.utc)
    t = (now - last_recalled).total_seconds() / 3600  # 時間単位
    S = entry["memory_strength"]
    return math.exp(-t / S)

def should_recall(entry: dict, query_keywords: list[str]) -> tuple[bool, float]:
    """エントリを想起すべきか判定（保持率×関連度）"""
    retention = compute_retention(entry)

    # 保持率が低すぎたら忘れたことにする（検索対象から除外）
    if retention < 0.05:
        return False, 0.0

    # キーワード関連度スコア（TF-IDFの簡易版）
    entry_kw = set(entry.get("keywords", []))
    query_kw = set(query_keywords)
    if not entry_kw:
        return False, 0.0
    relevance = len(entry_kw & query_kw) / len(entry_kw | query_kw)  # Jaccard係数

    score = retention * relevance
    return score > 0.1, score

def recall_entry(entry: dict) -> dict:
    """エントリを想起（記憶強度を更新）"""
    entry["last_recalled_at"] = datetime.now(timezone.utc).isoformat()
    entry["recall_count"] += 1
    entry["memory_strength"] = entry["recall_count"] + 1  # S = count + 1
    entry["retention_score"] = compute_retention(entry)
    return entry
```

### 想起の仕組み（index.js側）

```javascript
// askGemini() 内、プロンプト構築前に挿入
async function recallEpisodicMemory(userMessage, userId, env) {
  const yyyymm = new Date().toISOString().slice(0, 7).replace('-', '');
  const raw = await env.MEMORY_KV.get(`episodic:${userId}:${yyyymm}`);
  if (!raw) return { text: "", recalled: [] };

  const data = JSON.parse(raw);
  const queryKeywords = extractKeywords(userMessage);  // 簡易キーワード抽出

  // 関連エントリを検索・スコアリング
  const scored = data.entries
    .map(e => ({ entry: e, score: computeRelevanceScore(e, queryKeywords) }))
    .filter(x => x.score > 0.1)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);  // 上位3件

  if (scored.length === 0) return { text: "", recalled: [] };

  // 想起したエントリの記憶強度を更新
  const recalled = scored.map(x => recallEntry(x.entry));

  // プロンプト用テキストに変換
  const memoryText = recalled.map(e =>
    `- [${e.created_at.slice(0, 10)}] ${e.summary} (想起${e.recall_count}回目)`
  ).join('\n');

  return {
    text: `\n\n## 過去の会話で覚えていること\n${memoryText}`,
    recalled
  };
}
```

---

## 4. Layer 3 — 意味記憶（Semantic Memory / 人格知識）

### 概要

**「体に刻まれた知識」** = エピソード記憶が何度も想起されることで「概念」として昇格したもの。もはや「いつ・誰と話したか」という文脈は消え、「VibeちゃんがずっとKnowしていること」になります。

### 昇格条件（Episodic → Semantic）

```
以下の条件を全て満たしたエントリは自動的に意味記憶に昇格候補になる：

1. recall_count >= 5（5回以上想起されている）
2. 異なるユーザー/会話コンテキストで参照されている
3. retention_score > 0.5（まだ保持されている）
4. is_knowledge_worthy: true（価値判定フラグ = trueになっている）
```

### データ構造

```json
// data/character_knowledge/personality_layer.json
// （GitHub上に保存 = 全インスタンス共有・永続）
{
  "version": "1.0",
  "last_consolidated": "2026-03-03",
  "knowledge_entries": [
    {
      "id": "kw_001",
      "category": "claude_code",
      "title": "Claude CodeとMCPの関係",
      "content": "MCP（Model Context Protocol）はClaudeが外部ツールと通信するための標準プロトコル。ユーザーから何度も質問が来るほど重要な概念で、Vibeちゃんも自信を持って説明できる。",
      "confidence": 0.92,             // 自信係数（recall多いほど高い）
      "origin_count": 12,             // このナレッジが何回のエピソードから蒸留されたか
      "first_learned": "2026-02-01",
      "last_reinforced": "2026-03-03",
      "tags": ["mcp", "claude", "protocol", "tool-use"]
    },
    {
      "id": "kw_002",
      "category": "vibecoding",
      "title": "VibeCodingでよくあるエラーパターン",
      "content": "コンテキスト長超過、プロンプトインジェクション、APIレート制限の3つが頻出。特にコンテキスト長はユーザーが詰まりやすい。empathyを高めて対応する。",
      "confidence": 0.78,
      "origin_count": 7,
      "first_learned": "2026-02-15",
      "last_reinforced": "2026-03-01",
      "tags": ["vibecoding", "error", "context-length", "empathy"]
    }
  ],
  "user_personality_notes": [
    // ユーザー個別の特性メモ（誰が何に興味を持っているか）
    {
      "userId_hash": "abc123",          // ユーザーIDをハッシュ化（プライバシー保護）
      "traits": ["MCP詳しい", "エラー相談多い", "深夜帯利用"],
      "preferred_detail_level": "technical",
      "last_updated": "2026-03-03"
    }
  ]
}
```

### プロンプトへの注入（「体に刻まれた」感の演出）

```javascript
// buildSystemPrompt() の末尾に動的追加
function buildPersonalityKnowledgeSection(knowledge, relevantEntries) {
  if (!relevantEntries.length) return "";

  return `
## VibeちゃんがずっとKnowしていること（体に刻まれた知識）
${relevantEntries.map(k =>
  `- ${k.title}（自信度:${Math.round(k.confidence * 100)}%）: ${k.content}`
).join('\n')}

この知識はVibeちゃんにとって「当たり前に知っている」ことなので、
質問されたら自信を持って（でもキャラクターらしく）答えて。`;
}
```

---

## 5. RAGシステム設計（知識蓄積パイプライン）

### RAG とは何か

**R**etrieval **A**ugmented **G**eneration — 「検索して文脈に加える」仕組みです。

```
通常のLLM:
ユーザー質問 → [LLMのパラメータ内知識のみ] → 回答
                    （学習時のデータしか知らない）

RAG付きLLM:
ユーザー質問 → [関連知識を検索] → [質問 + 検索結果] → 回答
                    （リアルタイムで外部知識を参照できる）
```

### 本プロジェクトのRAG実装方針

ベクターDB（Pinecone等）は**有料・運用コストが高い**ため使わない。代わりに**BM25キーワード検索**を採用します。研究によるとBM25はOpenAIのEmbeddingと同等の検索精度を多くのケースで発揮します。

```
採用: BM25 / TF-IDF ベースのキーワード検索
不採用: ベクターDB（Pinecone, Weaviate, ChromaDB）
理由: 無料・追加インフラ不要・JSONファイルで完結
```

### 知識蓄積パイプライン（全自動）

```
① RSSフィード収集 (fetch_and_deliver.py) — 既存
    ↓
② 記事から知識抽出 (extract_knowledge.py) — 新規作成
    ↓ [Geminiでキーワード・要約・カテゴリ・価値スコアを生成]
    ↓
③ JSON知識ベースに保存 (data/knowledge_base/YYYY-MM/{category}.json)
    ↓
④ GitHub Actionsで定時実行 → git commit & push
    ↓
⑤ /ask コマンド時に GitHub Raw URLから取得して検索（RAG）
    ↓
⑥ 高価値・高頻度エントリを定期的に personality_layer.json へ統合 (consolidate.py) — 新規作成
```

### BM25検索の実装

```python
# scripts/extract_knowledge.py 内のキーワード検索部分

import math
from collections import Counter

def bm25_score(query_terms: list[str], doc_terms: list[str],
               k1: float = 1.5, b: float = 0.75, avg_doc_len: float = 50) -> float:
    """
    BM25スコア計算（ベクターDB不要の軽量版）

    k1: 単語頻度の飽和係数（1.2〜2.0が一般的）
    b:  文書長正規化係数（0.75が一般的）
    """
    doc_len = len(doc_terms)
    doc_counter = Counter(doc_terms)
    score = 0.0

    for term in query_terms:
        tf = doc_counter.get(term, 0)
        if tf == 0:
            continue
        # BM25公式
        idf = math.log((1 + 1) / (1 + tf))  # 簡易IDF
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))

    return score

def search_knowledge(query: str, knowledge_entries: list[dict], top_k: int = 3) -> list[dict]:
    """クエリに関連する知識を検索して上位top_k件を返す"""
    query_terms = extract_terms(query)  # 日本語形態素解析 or 単純分割

    scored = []
    for entry in knowledge_entries:
        doc_terms = entry.get("keywords", []) + extract_terms(entry.get("summary", ""))
        score = bm25_score(query_terms, doc_terms)
        if score > 0:
            scored.append((entry, score))

    return [e for e, _ in sorted(scored, key=lambda x: -x[1])[:top_k]]
```

### 記事の「価値スコア」判定

```python
def assess_knowledge_value(title: str, summary: str, gemini_key: str) -> dict:
    """
    Gemini APIで記事の知識価値を評価する

    返すJSON:
    {
      "is_worthy": true/false,   # Layer3に昇格させる価値があるか
      "importance": 0.85,        # 重要度スコア (0.0〜1.0)
      "category": "claude_code", # 分類
      "keywords": ["claude", "mcp"],
      "core_insight": "MCPがClaude Codeとどう統合されるかの詳細説明"
    }
    """
    prompt = f"""
    以下の技術記事を分析して、AIアシスタントとして知識として持つ価値があるかを評価してください。

    タイトル: {title}
    要約: {summary}

    JSON形式で回答:
    {{
      "is_worthy": true/false,
      "importance": 0.0〜1.0,
      "category": "claude_code|vibecoding|mcp|prompt_engineering|general",
      "keywords": ["キーワード1", "キーワード2"],
      "core_insight": "この記事の本質的な知見を50文字以内で"
    }}
    """
    # Gemini API呼び出し...
```

---

## 6. 実装フェーズ計画

### Phase 1（最小工数・最大効果）: Layer 1 のみ
**工数: S（1〜2時間）**

```
変更ファイル: worker/src/index.js, worker/wrangler.toml

1. wrangler.toml に SESSION_KV を追加
2. askGemini() で KV read/write
3. history[] を Gemini の contents に渡す
4. 24時間 TTL で自動削除

→ これだけで「前の会話を覚えている」が実現する
```

### Phase 2: RAG知識ベース構築
**工数: M（4〜8時間）**

```
新規ファイル:
- scripts/extract_knowledge.py
- data/knowledge_base/ (自動生成)

変更ファイル:
- .github/workflows/news-delivery.yml
- worker/src/index.js（RAG注入）

→ 記事を読むたびに知識が蓄積されていく
```

### Phase 3: Layer 2 エピソード記憶 + 忘却曲線
**工数: L（8〜16時間）**

```
新規ファイル:
- scripts/memory_manager.py
- worker/src/memory.js

→ 会話が記憶され、想起回数で強化される
```

### Phase 4: Layer 3 人格統合（consolidation）
**工数: L（8〜16時間）**

```
新規ファイル:
- scripts/consolidate_memory.py
- data/character_knowledge/personality_layer.json

→ 「体に刻まれた」知識として人格に統合される
```

---

## 7. ストレージ設計（無料枠内）

| データ | 保存先 | TTL | サイズ感 |
|--------|--------|-----|---------|
| セッション感情状態 + 会話履歴 | Cloudflare KV | 24h | ~5KB/user |
| エピソード記憶 | Cloudflare KV | 90日 | ~50KB/user |
| 月別知識ベース(RAG) | GitHub JSON | 永続 | ~500KB/月 |
| 人格統合知識 | GitHub JSON | 永続 | ~100KB |
| ユーザー特性メモ | Cloudflare KV | 180日 | ~2KB/user |

**Cloudflare KV 無料枠**: 1GB storage / 100,000 reads/day / 1,000 writes/day
**GitHub**: 1GB storage free（JSONなら実質無制限）

---

## 8. プロンプト最終形（全レイヤー統合後）

```
[システムプロンプト: Big Five + フェーズ + 感情数値]

## VibeちゃんがずっとKnowしていること（体に刻まれた知識）
- MCPとClaude Codeの関係（自信度:92%）: ...
- VibeCodingでよくあるエラー（自信度:78%）: ...

## 過去の会話で覚えていること
- [2026-03-01] MCPについて一緒に調べた（想起3回目）
- [2026-03-02] デプロイエラーで詰まっていた（想起1回目）

## 関連する最新情報（RAGから）
- [2026-03-03] Claude Code v1.5 リリース: MCPが大幅強化...

[会話履歴: 直近3往復]
User: Claude Codeの新しいMCPって何が変わったの？
Model: えっとね！...
User: ...（続き）
```

---

## 9. 設計の核心思想

**「記憶は繰り返しで強化される」**

エビングハウスの研究が示すように、人間も「一度覚えた知識は時間とともに薄れるが、想起するたびに長持ちするようになる」という特性を持ちます。本設計はこれをそのまま実装します。

- 話題に出るたびに `recall_count++`, `memory_strength++`
- 長期間参照されないと `retention_score` が下がり、やがて「忘れる」
- 特定の知識が何度も登場したら `personality_layer.json` に「定着」
- 定着した知識はVibeちゃんの「自信係数（confidence）」を恒常的に高める

これにより、よく話題になる分野ではVibeちゃんが**段々と自信を持って話せるようになり**、逆に久しく触れていない分野では**「うーん、最近そっち追えてないかも…」と正直に言える**、心理的リアリティのあるキャラクターが生まれます。

---

*このドキュメントは設計段階のものです。実装はPhase 1から順に進めてください。*
*参照: [MemoryBank論文](https://arxiv.org/abs/2305.10250) / [Mem0論文](https://arxiv.org/abs/2504.19413)*
