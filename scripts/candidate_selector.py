#!/usr/bin/env python3
"""
最終候補選定 + 静的要約生成 — composite_score上位から多様性を考慮して選定する。

公式ソース（release/official）は無条件で最優先配信し、
残り枠を通常記事でカテゴリ多様性を考慮して埋める。
AIを使わずRSS descriptionからHTMLタグを除去し、トリミングで要約を生成する。
"""

import logging
import re

from keyword_scorer import PRIORITY_CATEGORIES

logger = logging.getLogger(__name__)


def _generate_static_summary(summary_raw: str, max_length: int) -> str:
    """summary_rawからHTMLタグを除去し、先頭max_length文字+"…"でトリミング。"""
    clean = re.sub(r"<[^>]+>", "", summary_raw)
    # HTMLエンティティも除去
    clean = re.sub(r"&\w+;", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_length:
        return clean[:max_length] + "…"
    return clean if clean else "（要約なし）"


def select_and_summarize(articles: list[dict], config: dict) -> list[dict]:
    """最終配信候補を選定し、静的要約を付与する。

    - composite_score上位からmax_candidates件を選定
    - 同一カテゴリはmax_per_categoryまで
    - 候補0件時は全記事からcomposite_score最高の1件を補充

    Args:
        articles: 重複除去済み記事リスト（composite_score 付き）
        config: static_filtering セクションを含む設定dict

    Returns:
        最終配信候補リスト（summary 付き）
    """
    sf = config.get("static_filtering", {})
    max_candidates = sf.get("max_candidates", 5)
    max_per_category = sf.get("max_per_category", 2)
    # 公式ソース（release/official）はカテゴリごとに最大1件がデフォルト。
    # 複数リリースが一度に配信されるのを防ぐため、通常記事より厳しく制限する。
    max_per_priority_category = sf.get("max_per_priority_category", 1)
    summary_max_length = sf.get("summary_max_length", 120)

    # composite_score降順でソート済みのはずだが念のため
    sorted_articles = sorted(
        articles,
        key=lambda x: x.get("composite_score", 0),
        reverse=True,
    )

    # 公式ソースを通常記事より優先して選定（ただしカテゴリ上限あり）
    priority_articles = [
        a for a in sorted_articles
        if a.get("category", "") in PRIORITY_CATEGORIES
    ]
    normal_articles = [
        a for a in sorted_articles
        if a.get("category", "") not in PRIORITY_CATEGORIES
    ]

    selected = []
    # priority と normal で共通のカテゴリカウントを使用する
    category_count: dict[str, int] = {}

    for article in priority_articles:
        if len(selected) >= max_candidates:
            logger.debug(
                "除外(候補数上限-公式): max=%d | %s",
                max_candidates, article.get("title", ""),
            )
            continue

        cat = article.get("category", "other")
        if category_count.get(cat, 0) >= max_per_priority_category:
            logger.debug(
                "除外(公式カテゴリ上限): cat=%s, max=%d | %s",
                cat, max_per_priority_category, article.get("title", ""),
            )
            continue

        article["summary"] = _generate_static_summary(
            article.get("summary_raw", ""),
            summary_max_length,
        )
        article["relevance"] = article.get("static_relevance", 3)
        selected.append(article)
        category_count[cat] = category_count.get(cat, 0) + 1

    # 残り枠を通常記事でカテゴリ多様性を考慮して埋める

    for article in normal_articles:
        if len(selected) >= max_candidates:
            logger.debug(
                "除外(候補数上限): max=%d | %s",
                max_candidates, article.get("title", ""),
            )
            continue

        cat = article.get("category", "other")
        if category_count.get(cat, 0) >= max_per_category:
            logger.debug(
                "除外(カテゴリ上限): cat=%s, max=%d | %s",
                cat, max_per_category, article.get("title", ""),
            )
            continue

        article["summary"] = _generate_static_summary(
            article.get("summary_raw", ""),
            summary_max_length,
        )
        article["relevance"] = article.get("static_relevance", 3)

        selected.append(article)
        category_count[cat] = category_count.get(cat, 0) + 1

    # 安全弁: 候補0件時はcomposite_score最高の1件を補充
    if not selected and sorted_articles:
        fallback = sorted_articles[0]
        fallback["summary"] = _generate_static_summary(
            fallback.get("summary_raw", ""),
            summary_max_length,
        )
        fallback["relevance"] = fallback.get("static_relevance", 3)
        selected.append(fallback)
        logger.info("candidate_selector: 候補0件のためfallback適用 | %s", fallback.get("title", ""))

    logger.info(
        "candidate_selector: %d件中 %d件選定 (公式=%d)",
        len(articles), len(selected), len(priority_articles),
    )
    return selected
