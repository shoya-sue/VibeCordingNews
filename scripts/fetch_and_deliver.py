#!/usr/bin/env python3
"""
NewsAI-VibeCording: RSS Feed Collector & Discord Webhook Deliverer
GitHub Actions から定時実行される。
RSSフィードを巡回し、新着記事をDiscord Webhookに配信する。
配信済み記事は data/delivered.csv に保存して再配信を防止。
AIキャラクター「VibeちゃんBot」として配信。
"""

import csv
import fcntl
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from constants import JST
from config_validator import validate_config, ConfigValidationError
from keyword_scorer import score_articles
from dedup_filter import deduplicate
from candidate_selector import select_and_summarize

import feedparser
import requests

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Paths ───
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
DELIVERED_CSV = ROOT_DIR / "data" / "delivered.csv"

# ─── Environment Variables ───
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ─── Constants ───
CSV_FIELDNAMES = ["url", "title", "source", "delivered_at",
                   "static_relevance", "composite_score"]

# Discord API 上限値（https://discord.com/developers/docs/resources/message）
DISCORD_CONTENT_MAX = 2000
DISCORD_EMBED_TITLE_MAX = 256
DISCORD_EMBEDS_PER_MESSAGE = 10


def load_config() -> dict:
    """設定ファイルを読み込み、スキーマバリデーションを実施する"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"config.json not found at {CONFIG_PATH}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config.json: {e}")
        sys.exit(1)

    # 設定値の整合性チェック — 起動時に即座に問題を検出する
    try:
        validate_config(config)
    except ConfigValidationError as e:
        logger.error(f"config.json バリデーションエラー:\n{e}")
        sys.exit(1)

    return config


def _migrate_csv_header():
    """既存CSVにカラムが不足していればヘッダーを更新し既存行に空値を補完する。

    複数プロセスが同時実行した場合の二重書き込みを防ぐため、
    ロックファイルで排他制御する。
    """
    if not DELIVERED_CSV.exists() or DELIVERED_CSV.stat().st_size == 0:
        return
    lock_path = DELIVERED_CSV.with_suffix(".lock")
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            # ロック取得後に再チェック（他プロセスが先に migration 済みの場合を考慮）
            with open(DELIVERED_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing_fields = reader.fieldnames or []
                if set(CSV_FIELDNAMES) <= set(existing_fields):
                    return  # マイグレーション不要
                rows = list(reader)
            # 新カラムを追加して再書き込み
            with open(DELIVERED_CSV, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})
            logger.info(f"delivered.csv ヘッダーを更新: {CSV_FIELDNAMES}")
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def load_delivered() -> set:
    """配信済み記事URLをsetとして返す"""
    DELIVERED_CSV.parent.mkdir(parents=True, exist_ok=True)

    if not DELIVERED_CSV.exists() or DELIVERED_CSV.stat().st_size == 0:
        # ヘッダー付きの空CSVを作成
        with open(DELIVERED_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
        return set()

    # 既存CSVにカラムが不足していれば自動マイグレーション
    _migrate_csv_header()

    delivered = set()
    try:
        with open(DELIVERED_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("url", "").strip()
                if url:
                    delivered.add(url)
    except Exception as e:
        logger.warning(f"CSV読み込みエラー（続行します）: {e}")
    return delivered


def load_delivered_titles() -> list[str]:
    """配信済み記事のタイトル一覧を返す（類似度チェック用）"""
    if not DELIVERED_CSV.exists():
        return []
    titles = []
    try:
        with open(DELIVERED_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get("title", "").strip()
                if title:
                    titles.append(title)
    except Exception as e:
        logger.warning(f"タイトル読み込みエラー（続行します）: {e}")
    return titles


def _save_pipeline_debug(stage: str, articles: list[dict]):
    """パイプライン中間結果をJSONに保存（デバッグ用）"""
    pipeline_dir = ROOT_DIR / "data" / "pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    out_path = pipeline_dir / f"{stage}.json"
    # datetimeをISO文字列に変換
    serializable = []
    for a in articles:
        item = {}
        for k, v in a.items():
            if isinstance(v, datetime):
                item[k] = v.isoformat()
            else:
                item[k] = v
        serializable.append(item)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        logger.info(f"  パイプラインデバッグ: {out_path}")
    except Exception as e:
        logger.warning(f"  パイプラインデバッグ保存エラー: {e}")


def save_delivered(articles: list[dict]):
    """配信した記事をCSVに追記"""
    try:
        with open(DELIVERED_CSV, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            for article in articles:
                writer.writerow({
                    "url": article["url"],
                    "title": article["title"],
                    "source": article["source"],
                    "delivered_at": datetime.now(JST).isoformat(),
                    "static_relevance": article.get("static_relevance", ""),
                    "composite_score": article.get("composite_score", ""),
                })
    except Exception as e:
        logger.error(f"CSV書き込みエラー: {e}")


def parse_entry_time(entry) -> datetime:
    """feedparserエントリからUTC datetimeを安全に取得"""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return datetime.now(timezone.utc)


def fetch_feeds(config: dict) -> list[dict]:
    """全RSSフィードを巡回し、記事リストを返す"""
    all_articles = []
    for feed_conf in config["feeds"]:
        try:
            logger.info(f"  Fetching: {feed_conf['name']} ...")
            parsed = feedparser.parse(feed_conf["url"])

            if parsed.bozo and not parsed.entries:
                logger.warning(f"    Feed parse error: {parsed.bozo_exception}")
                continue

            for entry in parsed.entries[:10]:
                published = parse_entry_time(entry)
                author = getattr(entry, "author", "") or ""
                link = entry.get("link", "").strip()

                if not link:
                    continue

                all_articles.append({
                    "title": entry.get("title", "No Title").strip(),
                    "url": link,
                    "published": published,
                    "author": author,
                    "source": feed_conf["name"],
                    "category": feed_conf["category"],
                    "emoji": feed_conf["emoji"],
                    "lang": feed_conf["lang"],
                    "summary_raw": (entry.get("summary", "") or "")[:300],
                })
            logger.info(f"    → {len(parsed.entries)} entries found")
        except Exception as e:
            logger.warning(f"    Feed取得エラー {feed_conf['name']}: {e}")
            # 1つのフィードの失敗で全体を止めない
            continue
    return all_articles


def get_current_phase() -> dict:
    """JSTの現在時刻から配信フェーズを判定"""
    jst = datetime.now(JST)
    h = jst.hour
    if 6 <= h <= 8:
        return {"name": "early_morning", "tension": [40, 60], "style": "寝起きモード。眠そう"}
    elif 9 <= h <= 11:
        return {"name": "morning", "tension": [70, 90], "style": "活発モード。ハイテンション"}
    elif 12 <= h <= 17:
        return {"name": "afternoon", "tension": [60, 80], "style": "集中モード。落ち着いた解説"}
    elif 18 <= h <= 22:
        return {"name": "evening", "tension": [50, 70], "style": "まったりモード。優しいトーン"}
    else:
        return {"name": "late_night", "tension": [20, 40], "style": "眠たいモード。ぼそぼそ"}


# ─── Gemini responseSchema（要約+関連度を同時取得） ───
SUMMARY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {
            "type": "STRING",
            "description": "VTuber口調での記事要約（100文字以内）",
        },
        "relevance": {
            "type": "INTEGER",
            "description": "VibeCoding/Claude Codeコミュニティとの関連度（1-5）",
        },
    },
    "required": ["summary", "relevance"],
}

# 関連度スコアの評価基準（システムプロンプトに注入）
RELEVANCE_CRITERIA = """
## 関連度スコア (relevance) の基準
記事がVibeCoding/Claude Codeコミュニティにとってどれだけ有用かを1-5で評価してください。
- 5: Claude Code/VibeCodingの公式アップデート・リリース情報
- 4: AI駆動開発の実践Tips、MCP関連、AIエージェント活用事例
- 3: AI開発ツール全般（Copilot, Cursor等含む）、プロンプトエンジニアリング
- 2: 間接的に関連する話題、汎用的な入門・初心者向け記事
- 1: コミュニティとの関連が薄い、一般的なプログラミング記事
"""


def _make_fallback_result(summary_raw: str) -> dict:
    """Gemini APIが使えない場合のフォールバック結果を生成"""
    clean = re.sub(r"<[^>]+>", "", summary_raw)
    fallback_summary = clean[:150] + "..." if len(clean) > 150 else clean
    return {"summary": fallback_summary, "relevance": 3}


def summarize_with_gemini(title: str, summary_raw: str, config: dict) -> dict:
    """Gemini API で記事の要約と関連度を同時取得（VTuber心理モデルv2.0対応）

    Returns:
        dict: {"summary": str, "relevance": int}
    """
    if not GEMINI_API_KEY:
        return _make_fallback_result(summary_raw)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"

    # 配信フェーズに応じたシステムプロンプト構築
    phase = get_current_phase()
    base_prompt = config.get("character", {}).get(
        "system_prompt_summary",
        "技術記事を100文字以内で日本語要約してください。"
    )
    phase_context = f"\n\n## 現在の配信フェーズ\n- フェーズ: {phase['name']}\n- テンション範囲: {phase['tension'][0]}〜{phase['tension'][1]}\n- 口調: {phase['style']}"
    system_prompt = base_prompt + phase_context + RELEVANCE_CRITERIA

    try:
        resp = requests.post(url, json={
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [{
                "role": "user",
                "parts": [{"text": f"タイトル: {title}\n概要: {summary_raw[:200]}"}]
            }],
            "generationConfig": {
                "maxOutputTokens": 300,
                "temperature": 0.8,
                "responseMimeType": "application/json",
                "responseSchema": SUMMARY_SCHEMA,
            }
        }, timeout=15)

        if resp.status_code == 429:
            logger.warning("    Gemini API rate limit reached, using fallback")
            return _make_fallback_result(summary_raw)

        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        result = json.loads(text)

        # バリデーション: relevanceが1-5の範囲に収まるように
        relevance = result.get("relevance", 3)
        relevance = max(1, min(5, int(relevance)))

        return {
            "summary": result.get("summary", "")[:200],
            "relevance": relevance,
        }

    except requests.exceptions.Timeout:
        logger.warning("    Gemini API timeout")
    except requests.exceptions.RequestException as e:
        logger.warning(f"    Gemini API request error: {e}")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        logger.warning(f"    Gemini API response parse error: {e}")

    # フォールバック: 中間値(3)で通過させる
    return _make_fallback_result(summary_raw)


# 挨拶を5パーツ（greeting_word / tone / emoji / context / news_action）に分解。
# 各リストの積がパターン数になる（例: 6×6×6×5×5=5400通り/フェーズ）。
_GREETING_PARTS: dict[str, dict[str, list[str]]] = {
    "early_morning": {
        # 6×5×5×5×5 = 3750通り
        "greeting_word": ["ふぁ", "ん", "むにゃ", "うーん", "はっ", "zzZ"],
        "tone":          ["…おはよ…", "…おはようなの…", "…きたよ…", "…おはよ〜…", "…起きてる…"],
        "emoji":         ["☀️", "😪", "☕", "🌅", "💤"],
        "context":       ["まだ眠いけど", "ねむいけど", "寝ぼけてるけど", "目がしょぼしょぼだけど", "眠いけど"],
        "news_action":   ["ニュース届けないと…プロ意識…！", "頑張るね…", "来たよ…", "ニュースまとめてきたの…", "最新情報持ってきたの…"],
    },
    "morning": {
        # 5×5×5×4×5 = 2500通り
        "greeting_word": ["おはよ", "やほ", "やっほー", "おはようございます", "おはよ〜"],
        "tone":          ["〜！", "！！", "！✨", "〜！！！", "！"],
        "emoji":         ["✨", "🌅", "☀️", "🎉", "💫"],
        "context":       ["今日も", "朝から", "今日の朝も", "今朝も"],
        "news_action":   ["Vibeっていこー！", "いい記事あったよ！", "ニュースお届けするよ！", "VibeCodingニュースだよ！", "最新情報チェックしてこ！"],
    },
    "afternoon": {
        # 6×6×6×5×5 = 5400通り
        "greeting_word": ["やっほ", "こんにちは", "ねぇねぇ", "おーい", "はーい", "お昼もVibeってる"],
        "tone":          ["〜！", "！", "〜！？", "〜", "〜？", "！！"],
        "emoji":         ["☕", "📰", "✨", "🌤", "🌞", "💡"],
        "context":       ["午後の", "今日の午後も", "お昼の", "この時間の", "午後ゆっくり"],
        "news_action":   ["ニュースタイムだよ〜！", "記事まとめてきたよ！", "アツいニュースあったよ！", "旬の記事チェックしてこー！", "最新ニュースどうぞ！"],
    },
    "evening": {
        # 5×5×6×4×5 = 3000通り
        "greeting_word": ["お疲れさま", "おつかれ", "こんばんは", "やっと夕方だね", "おかえり"],
        "tone":          ["〜！", "！", "〜！？", "〜", "〜💦"],
        "emoji":         ["🌙", "✨", "🌆", "🍵", "🌇", "⭐"],
        "context":       ["今日も", "今日の", "夕方の", "一日の締めに"],
        "news_action":   ["面白い記事あったよ！", "ニュースタイムだよ！", "最新ニュースどうぞ！", "気になる記事まとめたよ〜", "アツいニュースあったよ！"],
    },
    "late_night": {
        # 4×4×5×4×5 = 1600通り
        "greeting_word": ["zzZ", "…むにゃ", "深夜ニュース", "zzZ…起きてる"],
        "tone":          ["…はっ！", "…あっ！", "…", "…よ…！"],
        "emoji":         ["📰", "🌙", "😴", "⭐", "🌃"],
        "context":       ["眠いけど", "深夜だけど", "こんな時間だけど", "頑張って"],
        "news_action":   ["ニュース…届けるの…", "来たよ…", "ありがとうね…", "まとめてきたの…", "お届けするの…"],
    },
}

# 件数表現・動詞を分解してランダム組み合わせ（例: 4×4=16通り）
_COUNT_PHRASES = [
    "**{count}件**",
    "{count}本の記事",
    "厳選 **{count}件**",
    "今日の **{count}件**",
]
_DELIVERY_VERBS = [
    "をお届けするよ！",
    "チェックしてみてね！",
    "持ってきたよ！読んでみて〜",
    "まとめたよ！気になるのある？",
]


def send_to_discord(articles: list[dict], config: dict):
    """Discord Webhookにembed形式で送信（キャラクター対応）"""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL not set. Printing to stdout instead.")
        for a in articles:
            logger.info(f"  [{a['emoji']}] {a['title']} - {a['url']}")
        return

    now_jst = datetime.now(JST)
    character = config.get("character", {})
    phase = get_current_phase()

    # 配信フェーズに応じた挨拶を5パーツで独立ランダム選択
    parts = _GREETING_PARTS.get(phase["name"], _GREETING_PARTS["morning"])
    greeting = (
        random.choice(parts["greeting_word"])
        + random.choice(parts["tone"])
        + random.choice(parts["emoji"])
        + " "
        + random.choice(parts["context"])
        + random.choice(parts["news_action"])
    )

    char_name = character.get("name", "NewsAI VibeCording")

    embeds = []
    for article in articles:
        raw_title = f"{article['emoji']} {article['title']}"
        # Discord embed title 上限を超える場合はトリム
        if len(raw_title) > DISCORD_EMBED_TITLE_MAX:
            raw_title = raw_title[:DISCORD_EMBED_TITLE_MAX - 1] + "…"
        embed = {
            "title": raw_title,
            "url": article["url"],
            "description": article.get("summary", ""),
            "color": config["discord"]["embed_color"],
            "fields": [
                {"name": "📌 ソース", "value": article["source"], "inline": True},
                {"name": "✍️ 著者", "value": article["author"] or "—", "inline": True},
            ],
            "footer": {"text": f"{char_name} • {article['category']}"},
        }
        # リリース記事にバージョン番号が抽出されていれば表示
        if article.get("version"):
            embed["fields"].append(
                {"name": "🔖 バージョン", "value": article["version"], "inline": True}
            )
        # timestamp は ISO 8601 文字列が必須
        if article.get("published"):
            embed["timestamp"] = article["published"].isoformat()
        embeds.append(embed)

    suffix = random.choice(_COUNT_PHRASES).format(count=len(articles)) + random.choice(_DELIVERY_VERBS)
    raw_content = f"{greeting} {suffix}"
    # Discord content 上限を超える場合はトリム
    if len(raw_content) > DISCORD_CONTENT_MAX:
        raw_content = raw_content[:DISCORD_CONTENT_MAX - 1] + "…"
    payload = {
        "content": raw_content,
        "username": char_name,
        "embeds": embeds[:DISCORD_EMBEDS_PER_MESSAGE],
    }

    avatar_url = character.get("avatar_url", "")
    if avatar_url:
        payload["avatar_url"] = avatar_url

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Discord配信完了: {len(articles)}件")
    except requests.exceptions.RequestException as e:
        logger.error(f"Discord配信エラー: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"  Response: {e.response.text[:500]}")
        sys.exit(1)


def main():
    logger.info("=" * 50)
    logger.info("NewsAI VibeCording - Feed Collector")
    logger.info(f"Time: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    logger.info("=" * 50)

    config = load_config()
    delivered = load_delivered()
    logger.info(f"配信済み記事数: {len(delivered)}")

    # 1. RSS収集
    logger.info("RSSフィード巡回中...")
    all_articles = fetch_feeds(config)
    logger.info(f"取得記事数: {len(all_articles)}")

    # 2. 重複除去
    new_articles = [a for a in all_articles if a["url"] and a["url"] not in delivered]
    logger.info(f"新着記事数: {len(new_articles)}")

    if not new_articles:
        logger.info("新着記事なし。配信をスキップします。")
        return

    # 3. 静的フィルタリングパイプライン or 従来フロー
    new_articles.sort(key=lambda x: x["published"], reverse=True)
    max_items = config["discord"]["max_items_per_delivery"]

    static_filtering = config.get("static_filtering", {})
    static_enabled = static_filtering.get("enabled", False)

    if static_enabled:
        # ─── 静的フィルタリングパイプライン（Gemini API呼び出し: 0回） ───
        logger.info("静的フィルタリングパイプライン開始...")
        delivered_titles = load_delivered_titles()

        # Stage 1: キーワードスコアリング
        scored = score_articles(new_articles, config)
        logger.info(f"  [Stage 1] キーワードスコアリング: {len(new_articles)}→{len(scored)}件")
        _save_pipeline_debug("scored", scored)

        # Stage 2: 類似タイトル重複排除
        deduped = deduplicate(scored, delivered_titles, config)
        logger.info(f"  [Stage 2] 重複排除: {len(scored)}→{len(deduped)}件")
        _save_pipeline_debug("deduped", deduped)

        # Stage 3: 最終候補選定＋静的要約生成
        selected = select_and_summarize(deduped, config)
        logger.info(f"  [Stage 3] 最終候補選定: {len(deduped)}→{len(selected)}件")
        _save_pipeline_debug("selected", selected)

        # ログ: 選定結果の詳細
        for a in selected:
            logger.info(
                f"  配信: [rel={a.get('static_relevance', '?')}, "
                f"score={a.get('composite_score', 0):.2f}] {a['title'][:50]}"
            )
    else:
        # ─── 従来フロー（Gemini API使用） ───
        filtering = config.get("filtering", {})
        filtering_enabled = filtering.get("enabled", False)

        if filtering_enabled:
            pool_size = filtering.get("candidate_pool_size", 8)
            candidates = new_articles[:pool_size]
        else:
            candidates = new_articles[:max_items]
        logger.info(f"要約候補: {len(candidates)}件 (フィルタリング: {'ON' if filtering_enabled else 'OFF'})")

        gemini_count = 0
        gemini_max = config["rate_limits"]["gemini_daily_max"]
        for article in candidates:
            if gemini_count < gemini_max:
                logger.info(f"  要約生成: {article['title'][:40]}...")
                result = summarize_with_gemini(
                    article["title"], article["summary_raw"], config
                )
                article["summary"] = result["summary"]
                article["relevance"] = result.get("relevance", 3)
                gemini_count += 1
                time.sleep(1)
            else:
                clean = re.sub(r"<[^>]+>", "", article["summary_raw"])
                article["summary"] = clean[:150]
                article["relevance"] = 3

        if filtering_enabled:
            threshold = filtering.get("relevance_threshold", 3)
            passed = [a for a in candidates if a.get("relevance", 0) >= threshold]
            excluded = [a for a in candidates if a.get("relevance", 0) < threshold]
            logger.info(f"関連度フィルタ通過: {len(passed)}/{len(candidates)}件 (閾値: {threshold})")
            for a in excluded:
                logger.info(f"  除外: [{a.get('relevance', '?')}] {a['title'][:50]}")
            selected = passed[:max_items]
        else:
            selected = candidates[:max_items]

    if not selected:
        logger.info("関連度フィルタ後に配信対象なし。配信をスキップします。")
        return

    logger.info(f"配信対象: {len(selected)}件")

    # 6. Discord配信
    logger.info("Discord Webhookに配信中...")
    send_to_discord(selected, config)

    # 7. 配信済み保存
    save_delivered(selected)
    logger.info("配信済みCSVを更新しました")

    logger.info("完了！")


if __name__ == "__main__":
    main()
