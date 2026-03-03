# Research Sources — NewsAI-VibeCording Memory/RAG Architecture

> 調査日: 2026-03-03
> 目的: VibeCordingBot の記憶システム・RAG 設計における理論的根拠の蓄積
> 対象コンポーネント: `worker/src/index.js` (Layer 1), `memory_manager.py` (Layer 2), `extract_knowledge.py` (Phase 2)

---

## 1. 記憶アーキテクチャ (Memory Architecture)

### 1.1 MemoryBank: Enhancing Large Language Models with Long-Term Memory
- **著者**: Wanjun Zhong, Lianghong Guo, Qiwei Cai, He Ye, Yanlin Wang
- **掲載**: AAAI 2024
- **arXiv**: https://arxiv.org/abs/2305.10250
- **採用箇所**: `memory_manager.py` の `compute_retention()`, `recall_entry()`

**核心的貢献**:
- Ebbinghaus 忘却曲線を LLM コンテキストに適用: `R(t) = e^(-t/S)`
- S の初期値 = 1.0、リコール時 S += 1 でシンプルに実装可能
- t = 0 (リコール時にリセット) で自然な記憶強化を再現
- 評価: DailyDialog で +2.0 BLEU、PersonaChat で +5% 一貫性向上

**本実装への改良点**:
- S の増分を固定値 1 ではなく SM-2 の EF ベースに (良い思い出しほど強化)
- `recall_boost = ef / 2.5` で EF の範囲 (1.3〜∞) を正規化

---

### 1.2 Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory
- **著者**: Prateek Chhikara, Dev Khant, Saket Aryan, Taranjeet Singh, Deshraj Yadav
- **arXiv**: https://arxiv.org/abs/2504.19413
- **発表**: 2025年
- **採用箇所**: 3 層アーキテクチャ設計、選択的記憶統合の考え方

**核心的貢献**:
- フルコンテキスト比で 26% 精度向上、91% レイテンシ削減
- エピソード記憶の「選択的統合」: 全履歴ではなく重要記憶のみ保持
- 記憶の CRUD 操作: Add / Update / Delete / Search
- ハイブリッドストレージ: Vector DB + Structured DB の組み合わせ

**本実装への適用**:
- 本実装は Vector DB の代わりに BM25 を採用 (追加インフラコストゼロ)
- 選択的統合 = `is_worthy` フラグ + `importance >= 3` の閾値

---

### 1.3 In-context Learning with Retrieved Demonstrations for Language Models
- **著者**: Shi et al.
- **採用箇所**: RAG パイプライン設計の理論的根拠

**核心的知見**:
- Few-shot 例示を動的に選択する In-context RAG は静的プロンプトより優れる
- BM25 による例示選択は Dense Retrieval と遜色ない性能を示す場合がある

---

## 2. 間隔反復学習 (Spaced Repetition)

### 2.1 SM-2 Algorithm (SuperMemo 2)
- **著者**: Piotr Wozniak
- **初出**: 1987年 (SuperMemo 2 実装)
- **公式ドキュメント**: https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results
- **採用箇所**: `memory_manager.py` の `recall_entry()`

**アルゴリズム詳細**:
```
EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
EF' = max(EF', 1.3)

インターバル:
  n=1: I=1 日
  n=2: I=6 日
  n>2: I = I_prev * EF'

q (品質スコア):
  5: 完璧に思い出せた
  4: 正確だが少し迷った
  3: 正確だが難しかった
  2: 間違えたが思い出せた
  1: 間違えた
  0: 全く覚えていない
```

**採用理由**:
- 40年以上実証されてきた間隔反復の標準アルゴリズム
- EF (Ease Factor) が記憶の「定着しやすさ」を自動調整
- q < 3 の場合は間隔リセット (忘れた場合は最初からやり直し)

---

### 2.2 Ebbinghaus Forgetting Curve
- **著者**: Hermann Ebbinghaus
- **原典**: "Über das Gedächtnis" (1885)
- **数式参考**: Murre & Dros (2015), PLoS ONE: "Replication and Analysis of Ebbinghaus' Forgetting Curve"
- **採用箇所**: `memory_manager.py` の `compute_retention()`

**数式**:
```
R(t) = e^(-t/S)
  R: 記憶保持率 (0.0〜1.0)
  t: 最後のリコールからの経過日数
  S: 記憶強度 (本実装: 初期=1.0, リコール時 += EF/2.5)
```

**実装上の注意点**:
- S = 0 でゼロ除算が発生するため `S = max(S, 0.1)` でガード
- t が負にならないよう `t = max((now - last).total_seconds() / 86400, 0)` でクランプ

---

## 3. 検索技術 (Retrieval / RAG)

### 3.1 Is BM25 Still Alive? A Comprehensive Evaluation of BM25 for Text Retrieval
- **arXiv**: https://arxiv.org/abs/2602.23368
- **発表**: 2026年2月
- **採用箇所**: `worker/src/index.js` の `bm25Score()`, `searchKnowledge()`, `memory_manager.py` の `bm25_search_memory()`

**核心的知見**:
- BM25 は OpenAI text-embedding-3-small と同等以上のケースが多数
- 特に技術ドキュメント・短文テキストでは BM25 が優位
- k1=1.5, b=0.75 が大多数のドメインで最適なデフォルト値
- 日本語バイグラムとの組み合わせで日本語検索に対応可能

**採用理由**:
- Cloudflare Workers ではベクトル DB (Pinecone, Qdrant) が利用不可
- 外部 Embedding API コールのレイテンシ・コストを回避
- JSON ファイルだけで知識ベースを構築できる (GitHub 無料プラン対応)

---

### 3.2 Probabilistic Relevance Framework: BM25 and Beyond
- **著者**: Robertson, S., & Zaragoza, H.
- **掲載**: Foundations and Trends in Information Retrieval, 2009
- **採用箇所**: BM25 実装の理論的根拠

**BM25 数式 (実装バージョン)**:
```javascript
// IDF (Inverse Document Frequency)
idf = log((N - n + 0.5) / (n + 0.5) + 1)

// TF normalization
tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))

// Score
score = Σ idf * tf_norm
```

**パラメータ選定根拠**:
- `k1 = 1.5`: 高頻度語のスコアを飽和させつつ適度に重視
- `b = 0.75`: 文書長正規化の強度 (0=なし, 1=完全正規化)
- 短い知識エントリ (平均40トークン) には b=0.75 が適切

---

### 3.3 Tokenization for Japanese BM25
- **参考実装**: MeCab, SudachiPy, fugashi
- **採用箇所**: `tokenize()` (index.js), `tokenize_memory()` (memory_manager.py)

**実装方針**:
- 外部形態素解析ライブラリは Cloudflare Workers 環境で利用不可
- 代替: 英数字トークン + 日本語バイグラム (2-gram) でカバレッジ確保
- 単漢字も追加してより細かいマッチングを実現
- Workers の WASM サポートを利用すれば将来的に TinySegmenter 統合も可能

---

## 4. LLM 出力構造化 (Structured Generation)

### 4.1 Gemini API — Structured Output with responseSchema
- **公式ドキュメント**: https://ai.google.dev/api/generate-content#v1beta.GenerationConfig
- **採用箇所**: `extract_knowledge.py` の `KNOWLEDGE_SCHEMA`

**重要パラメータ**:
```json
"generationConfig": {
  "responseMimeType": "application/json",
  "responseSchema": { ... JSON Schema ... },
  "temperature": 0.2
}
```

**採用理由**:
- `responseSchema` なしでは JSON の parse エラーが発生しやすい
- 低温度 (0.2) + responseSchema でほぼ 100% 有効 JSON を取得可能
- `enum` フィールドでカテゴリを制限することでハルシネーション抑制

---

### 4.2 JSON Mode in Large Language Models: Effectiveness and Limitations
- **知見**: structured generation は LLM の精度を下げず、後処理コストを大幅削減
- **採用箇所**: `extract_knowledge.py` の設計方針

---

## 5. クラウドインフラ (Infrastructure)

### 5.1 Cloudflare Workers KV — Persistent Storage
- **公式ドキュメント**: https://developers.cloudflare.com/kv/
- **採用箇所**: `worker/src/index.js` の `loadSession()`, `saveSession()`

**設計判断**:
```javascript
// KV は Eventually Consistent (書き込み後 ~60秒で全リージョンに伝播)
// TTL: 86400秒 (24時間) = ユーザーセッション保持期間
// フォールバック: KV 不可時は in-memory Map で継続動作
```

**制限事項**:
- 無料プラン: 読み取り 10万回/日, 書き込み 1万回/日
- 1キー最大 25MB
- 本実装では 1ユーザー = 1KVエントリ, セッション ~1KB → 無料枠内

---

### 5.2 Cloudflare Edge Cache for GitHub Raw URLs
- **公式ドキュメント**: https://developers.cloudflare.com/cache/
- **採用箇所**: `worker/src/index.js` の `fetchKnowledgeBase()`

```javascript
fetch(url, {
  cf: { cacheTtl: 300, cacheEverything: true }
})
// 5分間 Cloudflare Edge でキャッシュ → GitHub API レート制限回避
// コールドスタート時のみ実際の HTTP リクエスト発生
```

---

### 5.3 GitHub Actions as Serverless Scheduler
- **参考**: GitHub Actions Cron Syntax
- **採用箇所**: `.github/workflows/news-delivery.yml`

```yaml
schedule:
  - cron: "0 1 * * *"   # JST 10:00
  - cron: "0 6 * * *"   # JST 15:00
```

**採用理由**:
- GitHub Actions 無料枠: パブリックリポジトリは無制限
- Cloudflare Workers Cron Triggers は有料 (Workers Paid: $5/月) → 回避
- GitHub Raw URL + Edge Cache でコンテンツ配信コスト ゼロ

---

## 6. キャラクター設計・心理モデル

### 6.1 Big Five Personality Model (OCEAN)
- **参考**: Costa & McCrae (1992), "NEO Personality Inventory"
- **採用箇所**: `config.json` の `character.big_five`

**VibeCちゃんBotのスコア設定根拠**:
```
O (開放性):  9/10 — AI・技術への強い好奇心、新しいアイデアへの熱狂
C (誠実性):  6/10 — 中程度 (気まぐれさをキャラクターに持たせるため低め)
E (外向性):  8/10 — 配信者らしい明るさ、話すのが大好き
A (協調性):  8/10 — 視聴者への共感・サポート志向
N (神経症):  4/10 — 基本安定、但し技術的不確実性で軽い不安あり
```

---

### 6.2 VTuber Character Design — Psychological Authenticity
- **参考**: にじさんじ・ホロライブのキャラクター設計事例
- **採用箇所**: `config.json` の `character.vulnerability`, `speech_patterns`

**核心設計思想**:
- 完璧なAIではなく「脆さ」を持つキャラクターの方が親近感が高い
- 「ちょっと自信ないけど…」「たぶん〜」のような vulnerable 表現が重要
- 配信フェーズ (時間帯) によるテンション変化でリアリティを演出

---

### 6.3 Dynamic Emotion Engine — Valence-Arousal Model
- **参考**: Russell (1980), "A circumplex model of affect"
- **採用箇所**: `worker/src/index.js` の `computeEmotionState()`

**感情状態の 3 次元**:
```
tension:    0〜100 (覚醒度・活性化レベル)
curiosity:  0〜100 (好奇心・探索欲)
empathy:    0〜100 (共感・思いやり)
```

**状態遷移**:
- 減衰係数: 0.88 (各ターンで前状態の 88% に向かって収束)
- トリガー語: 技術用語 → curiosity↑, 困り系表現 → empathy↑, 感嘆符 → tension↑

---

## 7. 実装に影響した技術記事・ブログ

### 7.1 Ebbinghaus' Forgetting Curve Meets Transformers
- **著者**: Medium / Towards Data Science (複数記事)
- **内容**: LLM コンテキスト管理への Ebbinghaus 適用パターン集
- **活用点**: S の初期値・増分の実装例を参考

### 7.2 Building Memory for AI Agents (Lilian Weng's Blog)
- **URL**: https://lilianweng.github.io/posts/2023-06-23-agent/
- **内容**: Sensory Memory / Working Memory / Long-term Memory の3層分類
- **活用点**: 本実装の Layer 1/2/3 設計に直接対応

### 7.3 Cloudflare Workers + AI: Architecture Patterns
- **URL**: https://developers.cloudflare.com/workers-ai/
- **内容**: Workers での AI 統合パターン、KV とのデータフロー
- **活用点**: `loadSession` / `saveSession` の fallback パターン

---

## 8. 今後の調査候補

| 論文 / 技術 | 理由 | 優先度 |
|-------------|------|--------|
| FAISS (Facebook AI Similarity Search) | Workers WASM での Vector 検索可能性 | 中 |
| TinySegmenter.js | Workers 対応の日本語形態素解析 | 高 |
| LoRA fine-tuning for character consistency | キャラクターの一貫性向上 | 低 |
| GraphRAG (Microsoft, 2024) | 知識グラフベース RAG への発展 | 低 |
| Cognitive Load Theory | プロンプト最適化への応用 | 中 |
| RWKV / Mamba (State Space Models) | 長文コンテキスト効率化 | 低 |

---

## 9. 実装ファイルと論文の対応表

| ファイル | 採用論文・技術 |
|---------|---------------|
| `worker/src/index.js` - `bm25Score()` | Robertson & Zaragoza (2009), arxiv:2602.23368 |
| `worker/src/index.js` - `loadSession()` / `saveSession()` | Cloudflare KV Docs |
| `worker/src/index.js` - `fetchKnowledgeBase()` | Cloudflare Edge Cache Docs |
| `worker/src/index.js` - `computeEmotionState()` | Russell (1980), VTuber design |
| `scripts/memory_manager.py` - `compute_retention()` | MemoryBank (arxiv:2305.10250), Ebbinghaus (1885) |
| `scripts/memory_manager.py` - `recall_entry()` | SM-2 (Wozniak 1987), MemoryBank |
| `scripts/memory_manager.py` - `bm25_search_memory()` | arxiv:2602.23368 |
| `scripts/extract_knowledge.py` - `KNOWLEDGE_SCHEMA` | Gemini responseSchema Docs |
| `config.json` - `character.big_five` | Costa & McCrae (1992) |
| `config.json` - `phases`, `tension` | Russell (1980) Valence-Arousal |

---

*最終更新: 2026-03-03*
