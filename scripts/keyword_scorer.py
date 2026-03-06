#!/usr/bin/env python3
"""
キーワード関連度スコアリング — AIを使わず静的にVibeCoding関連度を判定する。

ティア別キーワード辞書でタイトル・本文をスキャンし、
ソースカテゴリ重みと鮮度を掛け合わせた composite_score を算出する。
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── ティア別キーワード辞書（小文字正規化済み） ───
# 最高ティアのマッチで static_relevance を決定
# 注意: 短いキーワード（2-3文字）は単語境界マッチが必要 → _WORD_BOUNDARY_KEYWORDS に登録
KEYWORD_TIERS = {
    5: [
        "claude code", "claudecode", "vibecoding",
        "バイブコーディング", "vibe coding",
    ],
    4: [
        "claude", "anthropic", "mcp", "model context protocol",
        "ai agent", "aiagent", "aiエージェント",
        "artifacts", "computer use", "tool use",
        "function calling", "agentic",
    ],
    3: [
        "copilot", "cursor", "ai開発", "llm",
        "プロンプトエンジニアリング", "prompt engineering",
        "cline", "windsurf", "devin",
        "rag", "retrieval augmented",
        "hooks", "worktree", "subagent",
    ],
    2: [
        "ai", "機械学習", "chatgpt", "生成ai",
        "generative ai", "machine learning",
    ],
}

# 短いキーワードは部分一致で誤検知するため、単語境界(\b)で判定する
# 例: "ai" が "wait", "domain", "explain" に含まれてしまう問題の防止
_WORD_BOUNDARY_KEYWORDS = {"ai", "mcp", "llm", "rag"}

# ソースカテゴリ別の重み
SOURCE_WEIGHTS = {
    "release": 1.5,
    "official": 1.5,
    "claude-code": 1.3,
    "vibecoding": 1.2,
}
DEFAULT_SOURCE_WEIGHT = 1.0

# ソースカテゴリによる最低relevance保証
# フィードの出所自体が関連性を担保するカテゴリに対して、
# キーワード不一致でも除外されないようにする
SOURCE_RELEVANCE_FLOOR = {
    "release": 5,    # Claude Code公式リリース → 最高優先
    "official": 5,   # Anthropic公式ニュース → 最高優先
    "claude-code": 4, # Claude Code専用フィード → 高優先
    "vibecoding": 4,  # VibeCoding専用フィード → 高優先
    "ai-agent": 3,   # AIエージェント専用フィード → 守備範囲内なので通過保証
}

# 公式ソース（他記事と比較不要、無条件で配信対象）
PRIORITY_CATEGORIES = {"release", "official"}

# タイトルマッチのボーナス倍率
TITLE_MATCH_BONUS = 1.5

# タイトル品質フィルタの設定
# バージョン番号のみ（v2.1.69, 2.1.69 等）は実質タイトルなしと判定
TITLE_MIN_CHARS = 5
_RE_VERSION_ONLY = re.compile(r"^v?\d+[\d.]+$", re.IGNORECASE)
# 日本語（ひらがな・カタカナ・漢字）または英字を含むか判定
_RE_HAS_WORD_CHAR = re.compile(r"[a-zA-Z\u3040-\u9fff\u30a0-\u30ff]")

# コードブロック検出 — 技術実装記事へのスコアボーナス
CODE_BLOCK_BONUS = 0.15
_RE_CODE_BLOCK = re.compile(r"```|<code[^>]*>", re.IGNORECASE)


def _is_title_valid(title: str) -> tuple[bool, str]:
    """タイトルの品質チェック。低品質タイトルを静的に除外する。

    Returns:
        (is_valid, reason): is_valid=False の場合、reason に除外理由
    """
    stripped = title.strip()
    if len(stripped) < TITLE_MIN_CHARS:
        return False, f"タイトルが短すぎる: {len(stripped)}文字"
    if _RE_VERSION_ONLY.match(stripped):
        return False, f"バージョン番号のみ: {stripped}"
    if not _RE_HAS_WORD_CHAR.search(stripped):
        return False, f"日本語・英字なし: {stripped}"
    return True, ""


def _has_code_block(summary_raw: str) -> bool:
    """summary_raw にコードブロック（``` または <code>）が含まれるか判定。"""
    return bool(_RE_CODE_BLOCK.search(summary_raw))


def _normalize(text: str) -> str:
    """検索用に正規化: 小文字化 + 全角→半角 + 余分な空白除去"""
    text = text.lower()
    # 全角英数を半角に変換
    text = text.translate(str.maketrans(
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    ))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _match_tier(text: str) -> int:
    """テキストにマッチする最高ティアを返す。マッチなしは1。"""
    normalized = _normalize(text)
    for tier in (5, 4, 3, 2):
        for keyword in KEYWORD_TIERS[tier]:
            if keyword in _WORD_BOUNDARY_KEYWORDS:
                # 短いキーワードは単語境界で判定し誤検知を防ぐ
                # re.ASCIIで日本語文字をワード境界として正しく扱う
                if re.search(rf"\b{re.escape(keyword)}\b", normalized, re.ASCII):
                    return tier
            elif keyword in normalized:
                return tier
    return 1


def _calc_freshness(
    published: Optional[datetime],
    decay_hours: float = 24.0,
    min_freshness: float = 0.2,
) -> float:
    """鮮度スコア: max(min_freshness, exp(-hours/decay_hours))

    Args:
        published: 記事の公開日時（UTC）
        decay_hours: 鮮度が 1/e に減衰する時間（config から設定可能）
        min_freshness: 鮮度スコアの下限値
    """
    if published is None:
        return 0.5
    now = datetime.now(timezone.utc)
    # naive datetimeへの対応
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    hours = max(0, (now - published).total_seconds() / 3600)
    return max(min_freshness, math.exp(-hours / decay_hours))


def score_articles(articles: list[dict], config: dict) -> list[dict]:
    """各記事にstatic_relevanceとcomposite_scoreを付与し、閾値未満を除外する。

    Args:
        articles: 記事リスト（title, summary_raw, category, published を含む）
        config: static_filtering セクションを含む設定dict

    Returns:
        閾値以上の記事リスト（static_relevance, composite_score 付き）
    """
    sf = config.get("static_filtering", {})
    min_relevance = sf.get("min_relevance", 3)
    freshness_decay_hours = sf.get("freshness_decay_hours", 24.0)
    freshness_min = sf.get("freshness_min", 0.2)

    scored = []
    filtered_count = 0
    for article in articles:
        title = article.get("title", "")
        summary_raw = article.get("summary_raw", "")
        category = article.get("category", "")

        # タイトル品質フィルタ（公式ソースはスキップ — バージョン番号のみタイトルが正常）
        if category not in PRIORITY_CATEGORIES:
            is_valid, reason = _is_title_valid(title)
            if not is_valid:
                filtered_count += 1
                logger.debug("除外(タイトル品質): %s | %s", reason, title)
                continue

        # タイトルとsummary_rawそれぞれのティアを判定
        title_tier = _match_tier(title)
        body_tier = _match_tier(summary_raw)

        # タイトルマッチはボーナス付きで比較し、最高を採用
        if title_tier >= body_tier:
            keyword_relevance = title_tier
            has_title_match = title_tier > 1
        else:
            keyword_relevance = body_tier
            has_title_match = False

        # ソースカテゴリの最低relevance保証を適用
        source_floor = SOURCE_RELEVANCE_FLOOR.get(category, 0)
        static_relevance = max(keyword_relevance, source_floor)

        # ソースカテゴリ重み
        source_weight = SOURCE_WEIGHTS.get(category, DEFAULT_SOURCE_WEIGHT)

        # 鮮度（減衰係数はconfigで調整可能）
        freshness = _calc_freshness(
            article.get("published"),
            decay_hours=freshness_decay_hours,
            min_freshness=freshness_min,
        )

        # composite_score 算出
        base = static_relevance * source_weight * freshness
        if has_title_match:
            base *= TITLE_MATCH_BONUS
        # コードブロックを含む記事は技術実装記事として優先度を上げる
        if _has_code_block(summary_raw):
            base += CODE_BLOCK_BONUS

        article["static_relevance"] = static_relevance
        article["composite_score"] = round(base, 3)

        if static_relevance >= min_relevance:
            scored.append(article)
        else:
            filtered_count += 1
            logger.debug(
                "除外(relevance不足): tier=%d, floor=%d → relevance=%d < %d | %s",
                keyword_relevance, source_floor, static_relevance,
                min_relevance, title,
            )

    # composite_score 降順ソート
    scored.sort(key=lambda x: x["composite_score"], reverse=True)
    logger.info(
        "keyword_scorer: %d件中 %d件通過, %d件除外",
        len(articles), len(scored), filtered_count,
    )
    return scored
