# NewsAI-VibeCording — 引き継ぎ & 機能対応状況ドキュメント

> **最終更新**: 2026-03-03
> **現行バージョン**: v3.0（記憶システム + RAG 実装済み）
> **次のマイルストーン**: v3.1（Cloudflare 環境セットアップ → 実動作確認）

---

## 📦 プロジェクト概要

VibeCoding / Claude Code / Claude Cowork の最新情報を自動収集し、Discord に定時配信する**無料フルサーバーレス** AI Bot システム。

| 項目 | 内容 |
|------|------|
| キャラクター | **VibeちゃんBot** — VTuber風、Big Five 心理モデル搭載 |
| 配信タイミング | JST 10:00 / 15:00（GitHub Actions cron） |
| AI エンジン | Gemini 2.0 Flash-Lite API（無料枠） |
| Bot ランタイム | Cloudflare Workers（無料枠） |
| 運用コスト | **¥0**（VPS・ドメイン不要） |

---

## 🗂 ディレクトリ構成と対応状況

```
NewsAI-VibeCording/
├── config.json                          ✅ v2.0 VTuber心理モデル設定
├── data/
│   ├── delivered.csv                    ✅ 配信済み記事URL（重複防止）
│   ├── processed_ids.json               ✅ 知識抽出済みID管理
│   ├── knowledge_base/                  ✅ RAG知識DB（配信後に自動蓄積）
│   │   ├── YYYY-MM/index.json           ✅ 月別知識エントリ
│   │   └── latest.json                  ✅ 検索用最新200件
│   ├── episodic_memory/
│   │   └── index.json                   ✅ エピソード記憶インデックス
│   └── character_knowledge/
│       └── personality_layer.json       ✅ Layer3 人格統合データ（長期蓄積後）
├── scripts/
│   ├── fetch_and_deliver.py             ✅ RSS収集→Gemini要約→Discord配信
│   ├── extract_knowledge.py             ✅ 記事→構造化知識抽出（BM25 RAG用）
│   ├── memory_manager.py                ✅ 忘却曲線エンジン（Ebbinghaus+SM-2）
│   ├── test_character.py                ✅ キャラクター8パターンテスト
│   └── requirements.txt                 ✅
├── worker/
│   ├── src/
│   │   ├── index.js                     ✅ v3.0 Discord Bot（BM25 RAG + KV会話履歴）
│   │   └── register-commands.js         ✅ スラッシュコマンド登録
│   ├── wrangler.toml                    ⚠️ KV ID・GITHUB_OWNER を要設定
│   └── package.json                     ✅
├── .github/workflows/
│   ├── news-delivery.yml                ✅ 定時配信 + 知識抽出 + 忘却更新
│   └── deploy-worker.yml                ✅ Worker 自動デプロイ
└── docs/
    ├── Memory_Architecture_Design.md    ✅ 記憶システム設計書
    ├── Research_Sources.md              ✅ 採用論文・技術ソース集
    ├── HANDOFF.md                       ✅ このファイル（引き継ぎ資料）
    └── TODO.yml                         ✅ 実装タスク管理
```

---

## ✅ 機能一覧と実装対応状況

### カテゴリ A — ニュース収集・配信

| # | 機能 | ファイル | 状態 | 備考 |
|---|------|---------|------|------|
| A-1 | RSS フィード収集 (8ソース) | fetch_and_deliver.py | ✅ 完成 | Zenn/GitHub/Qiita/DEV.to/HackerNews |
| A-2 | 重複配信防止 | fetch_and_deliver.py | ✅ 完成 | delivered.csv で URL 管理 |
| A-3 | Gemini による記事要約 | fetch_and_deliver.py | ✅ 完成 | フェーズ対応プロンプト |
| A-4 | Discord Webhook 配信 | fetch_and_deliver.py | ✅ 完成 | リッチメッセージ形式 |
| A-5 | GitHub Actions 定時実行 | news-delivery.yml | ✅ 完成 | JST 10:00 / 15:00 |
| A-6 | 知識自動抽出 (配信後) | news-delivery.yml + extract_knowledge.py | ✅ 完成 | 配信後に自動で RAG DB に追記 |

---

### カテゴリ B — Discord Bot スラッシュコマンド

| # | 機能 | ファイル | 状態 | 備考 |
|---|------|---------|------|------|
| B-1 | `/news` — 最新5件表示 | worker/src/index.js | ✅ 完成 | RSS から直接取得 |
| B-2 | `/ask` — AI 質問応答 | worker/src/index.js | ✅ 完成 | Gemini + 会話履歴 + RAG |
| B-3 | `/status` — Bot 状態表示 | worker/src/index.js | ✅ 完成 | 感情・KV・RAG 状態を表示 |
| B-4 | Ed25519 署名検証 | worker/src/index.js | ✅ 完成 | Discord セキュリティ要件 |
| B-5 | レート制限 (30req/h) | worker/src/index.js | ✅ 完成 | userId 単位で管理 |
| B-6 | スラッシュコマンド登録 | worker/src/register-commands.js | ✅ 完成 | 初回のみ手動実行が必要 |
| B-7 | Worker 自動デプロイ | deploy-worker.yml | ✅ 完成 | main push 時に自動デプロイ |

---

### カテゴリ C — キャラクター・感情エンジン

| # | 機能 | ファイル | 状態 | 備考 |
|---|------|---------|------|------|
| C-1 | Big Five 心理モデル (O/C/E/A/N) | config.json | ✅ 完成 | O:9/C:6/E:8/A:8/N:4 |
| C-2 | 5 フェーズ時間帯管理 | config.json + index.js | ✅ 完成 | morning/afternoon/evening 等 |
| C-3 | 動的感情スコアリング v2.1 | worker/src/index.js | ✅ 完成 | tension/curiosity/empathy を自動調整 |
| C-4 | 感情 → プロンプト変換 | worker/src/index.js | ✅ 完成 | buildEmotionPromptSection() |
| C-5 | 動的温度調整 | worker/src/index.js | ✅ 完成 | temp = 0.6 + (tension/100) × 0.4 |
| C-6 | 感情減衰 (0.88係数) | worker/src/index.js | ✅ 完成 | 毎ターン前状態の 88% に収束 |
| C-7 | 語尾パターン禁止 | worker/src/index.js | ✅ 完成 | 直前と同じ語尾を使わない |
| C-8 | キャラクターテスト | scripts/test_character.py | ✅ 完成 | 8シナリオ自動テスト |

---

### カテゴリ D — 記憶システム (Memory Architecture)

| # | 機能 | ファイル | 状態 | 備考 |
|---|------|---------|------|------|
| D-1 | Layer 1: 会話履歴 (直近3ターン) | worker/src/index.js | ✅ 完成 | Gemini contents[] に注入 |
| D-2 | Layer 1: Cloudflare KV 永続化 | worker/src/index.js | ✅ 完成 | TTL 24h、KV設定後に有効 |
| D-3 | Layer 1: in-memory フォールバック | worker/src/index.js | ✅ 完成 | KV 不在でも動作継続 |
| D-4 | Layer 2: エピソード記憶管理 | scripts/memory_manager.py | ✅ 完成 | Ebbinghaus + SM-2 実装 |
| D-5 | Layer 2: 忘却曲線 R=e^(-t/S) | scripts/memory_manager.py | ✅ 完成 | MemoryBank (AAAI 2024) 準拠 |
| D-6 | Layer 2: SM-2 間隔反復 | scripts/memory_manager.py | ✅ 完成 | EF 自動調整、次回レビュー日管理 |
| D-7 | Layer 2: BM25 記憶検索 | scripts/memory_manager.py | ✅ 完成 | 日本語バイグラム対応 |
| D-8 | Layer 2: GitHub Actions 定期 decay | news-delivery.yml | ✅ 完成 | 毎配信時に保持率を自動更新 |
| D-9 | Layer 3: Personality 層への統合 | scripts/memory_manager.py | ✅ 完成 | recall_count≥5 で自動昇格 |
| D-10 | Layer 3: personality_layer.json | data/character_knowledge/ | ⏳ 運用後 | 長期運用で自然に蓄積 |

---

### カテゴリ E — RAG (検索拡張生成)

| # | 機能 | ファイル | 状態 | 備考 |
|---|------|---------|------|------|
| E-1 | 知識抽出パイプライン | scripts/extract_knowledge.py | ✅ 完成 | Gemini responseSchema 使用 |
| E-2 | BM25 検索エンジン | worker/src/index.js | ✅ 完成 | k1=1.5, b=0.75、arxiv:2602.23368 |
| E-3 | 日本語トークナイザ | worker/src/index.js | ✅ 完成 | バイグラム + 英数字トークン |
| E-4 | GitHub Raw URL キャッシュ | worker/src/index.js | ✅ 完成 | 5分 Cloudflare Edge Cache |
| E-5 | RAG → プロンプト注入 | worker/src/index.js | ✅ 完成 | /ask 時に関連知識を system prompt に追加 |
| E-6 | 知識 DB 自動 commit | news-delivery.yml | ✅ 完成 | 配信後に GitHub に自動 push |
| E-7 | knowledge_base データ蓄積 | data/knowledge_base/ | ⏳ 運用後 | 配信が始まると自動で蓄積される |

---

### カテゴリ F — インフラ・環境設定

| # | 項目 | 設定場所 | 状態 | アクション |
|---|------|---------|------|-----------|
| F-1 | GEMINI_API_KEY | GitHub Secrets | ⚠️ 要設定 | Google AI Studio から取得 |
| F-2 | DISCORD_WEBHOOK_URL | GitHub Secrets | ⚠️ 要設定 | Discord サーバー設定から発行 |
| F-3 | DISCORD_APPLICATION_ID | wrangler secret | ⚠️ 要設定 | Discord Developer Portal |
| F-4 | DISCORD_PUBLIC_KEY | wrangler secret | ⚠️ 要設定 | Discord Developer Portal |
| F-5 | SESSION_KV (KV namespace) | wrangler.toml | ⚠️ 要設定 | `npx wrangler kv:namespace create SESSION_KV` |
| F-6 | MEMORY_KV (KV namespace) | wrangler.toml | ⚠️ 要設定 | `npx wrangler kv:namespace create MEMORY_KV` |
| F-7 | GITHUB_OWNER | wrangler.toml | ⚠️ 要設定 | 自分の GitHub ユーザー名に変更 |
| F-8 | スラッシュコマンド登録 | register-commands.js | ⚠️ 初回のみ | `node worker/src/register-commands.js` |

---

## 🚀 初回セットアップ手順

### Step 1: GitHub リポジトリ（5分）
```bash
# リポジトリを GitHub に push
git remote add origin https://github.com/YOUR_USERNAME/NewsAI-VibeCording.git
git push -u origin main

# GitHub Secrets を設定（Settings → Secrets → Actions）
# DISCORD_WEBHOOK_URL = https://discord.com/api/webhooks/...
# GEMINI_API_KEY      = AIza...
```

### Step 2: wrangler.toml の修正（2分）
```toml
# worker/wrangler.toml の以下2箇所を書き換える
[vars]
GITHUB_OWNER = "your-github-username"   # ← 自分のユーザー名

[[kv_namespaces]]
binding = "SESSION_KV"
id = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # ← Step 3 で取得

[[kv_namespaces]]
binding = "MEMORY_KV"
id = "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"  # ← Step 3 で取得
```

### Step 3: Cloudflare 設定（15分）
```bash
# KV ネームスペース作成（表示された ID を wrangler.toml に記入）
cd worker
npx wrangler kv:namespace create SESSION_KV
npx wrangler kv:namespace create MEMORY_KV

# Secrets を設定
npx wrangler secret put DISCORD_APPLICATION_ID
npx wrangler secret put DISCORD_PUBLIC_KEY
npx wrangler secret put GEMINI_API_KEY

# Worker デプロイ
npx wrangler deploy
```

### Step 4: Discord Bot 設定（10分）
```
1. https://discord.com/developers/applications でアプリ作成
2. Application ID と Public Key をメモ → Step 3 の Secrets に使用
3. Worker の URL を Interactions Endpoint URL に設定
4. Bot をサーバーに招待
```

### Step 5: スラッシュコマンド登録（1分）
```bash
cd worker
DISCORD_APPLICATION_ID=xxx DISCORD_BOT_TOKEN=yyy node src/register-commands.js
```

---

## 📐 アーキテクチャ図

```
【定時配信フロー】(JST 10:00 / 15:00)
GitHub Actions
  └── fetch_and_deliver.py
        ├── RSS 8ソース取得
        ├── Gemini で要約
        ├── Discord Webhook 配信
        ├── delivered.csv 更新
        └── extract_knowledge.py
              ├── 未処理記事を Gemini で構造化
              ├── data/knowledge_base/YYYY-MM/index.json に保存
              ├── data/knowledge_base/latest.json を再生成
              ├── memory_manager.py decay (忘却更新)
              └── git commit & push

【/ask コマンドフロー】
Discord ユーザー
  └── /ask "Claude Code って何ができる？"
        └── Cloudflare Worker (index.js)
              ├── レート制限チェック
              ├── loadSession(userId) → KV / in-memory
              ├── computeEmotionState() → tension/curiosity/empathy
              ├── fetchKnowledgeBase() → GitHub latest.json (5分キャッシュ)
              ├── searchKnowledge(query) → BM25 上位3件
              ├── buildSystemPrompt() + emotionSection + ragSection
              ├── Gemini API (contents[] に会話履歴 + 新メッセージ)
              ├── saveSession(userId) → KV (TTL 24h)
              └── Discord にレスポンス返却
```

---

## 📚 関連ドキュメント

| ファイル | 内容 |
|---------|------|
| `docs/Memory_Architecture_Design.md` | 3層記憶システムの設計書（数式・データ構造・実装計画） |
| `docs/Research_Sources.md` | 採用した論文・技術の根拠と参考文献一覧 |
| `docs/NewsAI-VibeCording_Presentation.pptx` | プロジェクト説明スライド (7枚) |
| `docs/Feasibility_Report_KnowledgeAndDialog.docx` | 知識蓄積・対話システムの実現可能性レポート |
| `TODO.yml` | 実装タスクの詳細管理ファイル |

---

## 🔬 採用技術・論文

| 技術 | 論文/ソース | 採用箇所 |
|------|-----------|---------|
| Ebbinghaus 忘却曲線 | MemoryBank (AAAI 2024, arxiv:2305.10250) | memory_manager.py |
| SM-2 間隔反復 | Wozniak (1987), SuperMemo | memory_manager.py |
| BM25 検索 | Robertson & Zaragoza (2009), arxiv:2602.23368 | index.js, memory_manager.py |
| 構造化出力 | Gemini responseSchema Docs | extract_knowledge.py |
| エピソード記憶 | Mem0 (arxiv:2504.19413) | アーキテクチャ設計 |
| 感情モデル | Russell (1980) Valence-Arousal | computeEmotionState() |
| Big Five | Costa & McCrae (1992) | config.json |
