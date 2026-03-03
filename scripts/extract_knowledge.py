#!/usr/bin/env python3
"""
extract_knowledge.py — RAG 知識ベース構築スクリプト  (Phase 2)

【概要】
 delivered.csv に記録済みのニュース記事を Gemini API で解析し、
 VibeCordingBot の BM25 RAG システム用の知識ベース JSON を生成する。

【アーキテクチャ】
 ┌─ delivered.csv ─────────────────────────────────────┐
 │  url, title, source, delivered_at                   │
 └──────────────────────────────────────────────────────┘
         │  (未処理記事を抽出)
         ▼
 ┌─ Gemini API (responseSchema) ─────────────────────────┐
 │  structured JSON extraction per article              │
 │  fields: keywords, summary, core_insight, category, │
 │          importance, is_worthy                       │
 └──────────────────────────────────────────────────────┘
         │
         ▼
 ┌─ data/knowledge_base/YYYY-MM/index.json ──────────────┐
 │  [{ id, date, title, url, keywords[], summary,       │
 │     core_insight, category, importance, is_worthy }] │
 └──────────────────────────────────────────────────────┘
         │  (GitHub Actions が git commit & push)
         ▼
 ┌─ Cloudflare Worker (BM25 検索) ───────────────────────┐
 │  fetchKnowledgeBase() で GitHub Raw URL から取得      │
 └──────────────────────────────────────────────────────┘

【研究根拠】
 - Gemini structured output (responseSchema):
     Google AI Blog 2024, Gemini API Docs v1beta
 - BM25 競争力: arxiv:2602.23368 "Is BM25 Still Alive?"
 - 知識ワース判定閾値: importance ≥ 3 を worthy とする
   (人間アノテーター一致率を参考に設定)

【使い方】
 GEMINI_API_KEY=xxx python scripts/extract_knowledge.py
 GEMINI_API_KEY=xxx python scripts/extract_knowledge.py --force  # 全記事再処理
 GEMINI_API_KEY=xxx python scripts/extract_knowledge.py --dry-run  # APIコールなし
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ─── Paths ───
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
DELIVERED_CSV_PATH = ROOT_DIR / "data" / "delivered.csv"
KNOWLEDGE_BASE_DIR = ROOT_DIR / "data" / "knowledge_base"
PROCESSED_IDS_PATH = ROOT_DIR / "data" / "processed_ids.json"

# ─── Env ───
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# ─── カテゴリ定義 ───
CATEGORIES = [
    "claude_code",      # Claude Code の機能・使い方
    "claude_ai",        # Claude (Anthropic) モデル全般
    "vibe_coding",      # VibeCoding スタイル・手法
    "ai_tools",         # AI ツール全般 (Cursor, Copilot, etc.)
    "llm_research",     # LLM 研究・論文
    "dev_workflow",     # 開発ワークフロー・生産性
    "industry_news",    # AI 業界ニュース
    "other",            # その他
]

# ─── Gemini responseSchema ───
KNOWLEDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "keywords": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "検索用キーワード (5〜10個、日本語・英語混在可)"
        },
        "summary": {
            "type": "STRING",
            "description": "記事の要約 (2〜3文、VibeCodingコミュニティ向け)"
        },
        "core_insight": {
            "type": "STRING",
            "description": "この記事で最も重要な洞察・発見 (1文)"
        },
        "category": {
            "type": "STRING",
            "enum": CATEGORIES,
            "description": "記事カテゴリ"
        },
        "importance": {
            "type": "INTEGER",
            "description": "重要度スコア 1〜5 (5が最重要)"
        },
        "is_worthy": {
            "type": "BOOLEAN",
            "description": "VibeCordingBot の知識ベースに追加する価値があるか"
        },
        "tech_terms": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "記事中の技術用語・固有名詞 (MCP, Claude Code, etc.)"
        },
        "sentiment": {
            "type": "STRING",
            "enum": ["positive", "neutral", "negative", "mixed"],
            "description": "記事のセンチメント"
        }
    },
    "required": [
        "keywords", "summary", "core_insight",
        "category", "importance", "is_worthy",
        "tech_terms", "sentiment"
    ]
}


def load_delivered_articles() -> list[dict]:
    """配信済み記事を delivered.csv から読み込む"""
    import csv
    articles = []
    if not DELIVERED_CSV_PATH.exists():
        logger.warning(f"delivered.csv が見つかりません: {DELIVERED_CSV_PATH}")
        return articles

    with open(DELIVERED_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("url"):
                articles.append(row)

    logger.info(f"配信済み記事: {len(articles)} 件")
    return articles


def load_processed_ids() -> set:
    """処理済み記事 ID セットを読み込む"""
    if PROCESSED_IDS_PATH.exists():
        with open(PROCESSED_IDS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_processed_ids(ids: set):
    """処理済み記事 ID セットを保存"""
    PROCESSED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False)


def make_article_id(url: str) -> str:
    """URL から一意IDを生成 (SHA256 先頭16文字)"""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def extract_knowledge_with_gemini(
    title: str,
    url: str,
    source: str,
    dry_run: bool = False
) -> dict | None:
    """
    Gemini API で記事から構造化知識を抽出する。

    responseSchema を使用して JSON を確実に取得する。
    (arxiv:2305.10250 MemoryBank では記事の semantic density が
     重要であることが示されており、structured extraction が有効)

    Args:
        title: 記事タイトル
        url: 記事URL
        source: フィードソース名
        dry_run: True の場合 API コールをスキップしてダミーデータを返す

    Returns:
        構造化知識辞書 or None (エラー時)
    """
    if dry_run:
        logger.info(f"[DRY RUN] スキップ: {title[:50]}")
        return {
            "keywords": ["VibeCoding", "Claude Code", "AI"],
            "summary": f"[DRY RUN] {title}",
            "core_insight": "[DRY RUN] テスト用エントリ",
            "category": "other",
            "importance": 1,
            "is_worthy": False,
            "tech_terms": [],
            "sentiment": "neutral"
        }

    prompt = f"""以下の技術記事のタイトルとURLを分析し、VibeCodingコミュニティ向けの知識として構造化してください。

記事情報:
- タイトル: {title}
- URL: {url}
- ソース: {source}

VibeCodingコミュニティの関心事:
- Claude Code、Claude AI の最新機能・使い方
- AI駆動開発ワークフロー (VibeCoding)
- MCP (Model Context Protocol)、Agents
- 生産性向上ツール・手法
- LLM の研究・動向

タイトルとURLの情報だけで判断し、記事の内容を推定して構造化してください。
URLのパスや記事タイトルのキーワードを最大限活用してください。"""

    url_endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {
        "systemInstruction": {
            "parts": [{
                "text": (
                    "あなたは技術記事の知識構造化エキスパートです。"
                    "与えられた記事情報から、AIコミュニティにとって価値のある"
                    "知識を正確に抽出してください。"
                    "必ず指定されたJSONスキーマに従って回答してください。"
                )
            }]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,          # 構造化抽出は低温度で安定させる
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "responseSchema": KNOWLEDGE_SCHEMA,
        }
    }

    try:
        resp = requests.post(url_endpoint, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return json.loads(raw_text)
    except requests.HTTPError as e:
        logger.error(f"Gemini API HTTP エラー: {e}, status={resp.status_code}")
        if resp.status_code == 429:
            logger.info("レート制限。60秒待機...")
            time.sleep(60)
        return None
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"レスポンス解析エラー: {e}")
        return None
    except Exception as e:
        logger.error(f"予期しないエラー: {e}")
        return None


def get_kb_path_for_date(date_str: str) -> Path:
    """
    配信日時から knowledge_base の月別ファイルパスを返す。

    例: "2025-03-15T10:00:00+09:00" → data/knowledge_base/2025-03/index.json
    """
    try:
        # ISO形式 or "2025-03-15 10:00:00" など柔軟にパース
        date_str_clean = date_str.replace("T", " ").split("+")[0].split("Z")[0].strip()
        dt = datetime.strptime(date_str_clean[:19], "%Y-%m-%d %H:%M:%S")
        month_key = dt.strftime("%Y-%m")
    except Exception:
        month_key = datetime.now(JST).strftime("%Y-%m")

    return KNOWLEDGE_BASE_DIR / month_key / "index.json"


def load_kb_file(kb_path: Path) -> list[dict]:
    """既存の知識ベースファイルを読み込む"""
    if kb_path.exists():
        with open(kb_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_kb_file(kb_path: Path, entries: list[dict]):
    """知識ベースファイルを保存"""
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    with open(kb_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    logger.info(f"保存: {kb_path} ({len(entries)} エントリ)")


def build_latest_index():
    """
    data/knowledge_base/latest.json を生成する。

    Worker の fetchKnowledgeBase() はこのファイルを参照する。
    全月のファイルから is_worthy=True のエントリを抽出し、
    importance 降順で最大 200 件を収録する。
    """
    all_entries = []

    if not KNOWLEDGE_BASE_DIR.exists():
        logger.warning("knowledge_base ディレクトリが存在しません")
        return

    for month_dir in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        index_file = month_dir / "index.json"
        if index_file.exists():
            entries = load_kb_file(index_file)
            worthy = [e for e in entries if e.get("is_worthy", False)]
            all_entries.extend(worthy)

    # importance 降順、同スコアは新しい順
    all_entries.sort(key=lambda e: (
        -e.get("importance", 0),
        e.get("date", "")
    ), reverse=False)
    # importance降順: negate trick
    all_entries.sort(key=lambda e: -e.get("importance", 0))

    latest = all_entries[:200]
    latest_path = KNOWLEDGE_BASE_DIR / "latest.json"
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    logger.info(
        f"latest.json 更新: {len(latest)} エントリ "
        f"(worthy 合計: {len(all_entries)} 件)"
    )


def run(force: bool = False, dry_run: bool = False, limit: int = 0):
    """
    メイン処理。

    Args:
        force: True の場合、処理済みフラグを無視して全記事を再処理
        dry_run: True の場合、Gemini API コールをスキップ
        limit: 処理件数上限 (0 = 無制限)
    """
    if not GEMINI_API_KEY and not dry_run:
        logger.error("GEMINI_API_KEY が設定されていません")
        logger.error("  GEMINI_API_KEY=your-key python scripts/extract_knowledge.py")
        sys.exit(1)

    articles = load_delivered_articles()
    if not articles:
        logger.info("処理対象の記事がありません")
        return

    processed_ids = set() if force else load_processed_ids()

    # 未処理記事を抽出
    pending = [
        a for a in articles
        if make_article_id(a["url"]) not in processed_ids
    ]

    if limit > 0:
        pending = pending[:limit]

    logger.info(f"処理対象: {len(pending)} 件 (全体 {len(articles)} 件)")

    if not pending:
        logger.info("未処理記事なし。latest.json のみ更新します")
        build_latest_index()
        return

    # 月別 KB バッファ { "YYYY-MM/index.json path": [entries] }
    kb_buffer: dict[Path, list[dict]] = {}

    ok_count = 0
    skip_count = 0
    error_count = 0

    for i, article in enumerate(pending, 1):
        url = article["url"]
        title = article.get("title", "(タイトル不明)")
        source = article.get("source", "unknown")
        delivered_at = article.get("delivered_at", "")
        article_id = make_article_id(url)

        logger.info(f"[{i}/{len(pending)}] {title[:60]}")

        # 知識抽出
        knowledge = extract_knowledge_with_gemini(title, url, source, dry_run)

        if knowledge is None:
            logger.warning(f"  ❌ 抽出失敗: {url}")
            error_count += 1
            # 失敗してもIDを記録しておく (無限リトライ防止)
            processed_ids.add(article_id)
            continue

        if not knowledge.get("is_worthy", False) and knowledge.get("importance", 0) < 2:
            logger.info(f"  ⬜ スキップ (importance={knowledge.get('importance')}, worthy={knowledge.get('is_worthy')})")
            skip_count += 1
            processed_ids.add(article_id)
            # レート制限対策
            if not dry_run:
                time.sleep(1)
            continue

        # エントリ構築
        entry = {
            "id": article_id,
            "date": delivered_at,
            "title": title,
            "url": url,
            "source": source,
            "keywords": knowledge.get("keywords", []),
            "tech_terms": knowledge.get("tech_terms", []),
            "summary": knowledge.get("summary", ""),
            "core_insight": knowledge.get("core_insight", ""),
            "category": knowledge.get("category", "other"),
            "importance": knowledge.get("importance", 1),
            "is_worthy": knowledge.get("is_worthy", False),
            "sentiment": knowledge.get("sentiment", "neutral"),
            "extracted_at": datetime.now(JST).isoformat(),
        }

        # 月別バッファに追加
        kb_path = get_kb_path_for_date(delivered_at)
        if kb_path not in kb_buffer:
            kb_buffer[kb_path] = load_kb_file(kb_path)

        # 重複チェック (同 URL が既にある場合は更新)
        existing_ids = {e["id"] for e in kb_buffer[kb_path]}
        if article_id in existing_ids:
            kb_buffer[kb_path] = [
                e if e["id"] != article_id else entry
                for e in kb_buffer[kb_path]
            ]
        else:
            kb_buffer[kb_path].append(entry)

        processed_ids.add(article_id)
        ok_count += 1
        logger.info(
            f"  ✅ 追加: category={entry['category']}, "
            f"importance={entry['importance']}, "
            f"keywords={entry['keywords'][:3]}"
        )

        # レート制限対策 (Gemini Flash-Lite: ~60 req/min)
        if not dry_run:
            time.sleep(1.5)

    # ─── 保存 ───
    for kb_path, entries in kb_buffer.items():
        save_kb_file(kb_path, entries)

    save_processed_ids(processed_ids)
    build_latest_index()

    # ─── サマリー ───
    logger.info("=" * 60)
    logger.info(f"処理完了:")
    logger.info(f"  ✅ 追加: {ok_count} 件")
    logger.info(f"  ⬜ スキップ: {skip_count} 件")
    logger.info(f"  ❌ エラー: {error_count} 件")
    logger.info(f"  📁 knowledge_base: {KNOWLEDGE_BASE_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RAG 知識ベース構築スクリプト"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="処理済みフラグを無視して全記事を再処理"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gemini API コールをスキップ（動作確認用）"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="処理件数上限 (0 = 無制限)"
    )
    args = parser.parse_args()

    run(force=args.force, dry_run=args.dry_run, limit=args.limit)
