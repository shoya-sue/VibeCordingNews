#!/usr/bin/env python3
"""
類似記事重複排除 — 文字バイグラムのJaccard類似度で重複をクラスタリングする。

同一ニュースが複数フィードで配信されるケースを排除し、
過去配信済みタイトルとの類似度チェックも行う。
公式ソース（release/official）は記事間重複排除をスキップする。
"""

import logging

from keyword_scorer import PRIORITY_CATEGORIES

logger = logging.getLogger(__name__)


def _char_bigrams(text: str) -> set[str]:
    """文字列から文字バイグラム集合を生成する。空白・記号は除去。"""
    # 記号・空白を除去して連続文字列にする
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch > "\u3000")
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard類似度を計算する。"""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def deduplicate(
    articles: list[dict],
    delivered_titles: list[str],
    config: dict,
) -> list[dict]:
    """類似タイトルの重複を排除する。

    1. 過去配信タイトルとの類似度 >= delivered_similarity_threshold の記事を除外
    2. 記事間で類似度 >= similarity_threshold のペアをクラスタリング
    3. 各クラスタから composite_score 最高の1件を残す

    Args:
        articles: スコア付き記事リスト（composite_score 付き）
        delivered_titles: 過去配信済み記事のタイトル一覧
        config: static_filtering セクションを含む設定dict

    Returns:
        重複除去済み記事リスト
    """
    sf = config.get("static_filtering", {})
    sim_threshold = sf.get("similarity_threshold", 0.4)
    delivered_threshold = sf.get("delivered_similarity_threshold", 0.5)

    # 過去配信タイトルのバイグラムを事前計算
    delivered_bigrams = [_char_bigrams(t) for t in delivered_titles]

    # Stage 1: 過去配信との類似チェック
    fresh = []
    delivered_dup_count = 0
    for article in articles:
        title = article.get("title", "")
        title_bigrams = _char_bigrams(title)
        is_duplicate = False
        for idx, d_bg in enumerate(delivered_bigrams):
            sim = _jaccard(title_bigrams, d_bg)
            if sim >= delivered_threshold:
                is_duplicate = True
                logger.debug(
                    "除外(配信済み類似): sim=%.2f >= %.2f | %s ≈ %s",
                    sim, delivered_threshold, title, delivered_titles[idx],
                )
                delivered_dup_count += 1
                break
        if not is_duplicate:
            article["_bigrams"] = title_bigrams
            fresh.append(article)

    # Stage 2: 記事間の類似クラスタリング（貪欲法）
    # 公式ソースは比較不要で無条件通過させる
    # composite_score降順で処理し、先に出たものをクラスタ代表とする
    fresh.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    priority = []
    normal = []
    for article in fresh:
        if article.get("category", "") in PRIORITY_CATEGORIES:
            priority.append(article)
        else:
            normal.append(article)

    # 通常記事のみクラスタリング対象
    result = list(priority)
    used = set()

    for i, article in enumerate(normal):
        if i in used:
            continue
        result.append(article)
        for j in range(i + 1, len(normal)):
            if j in used:
                continue
            sim = _jaccard(article["_bigrams"], normal[j]["_bigrams"])
            if sim >= sim_threshold:
                used.add(j)
                logger.debug(
                    "除外(記事間類似): sim=%.2f >= %.2f | %s ≈ %s",
                    sim, sim_threshold,
                    normal[j].get("title", ""), article.get("title", ""),
                )

    # 一時フィールドを除去
    for article in result:
        article.pop("_bigrams", None)

    inter_dup_count = len(used)
    logger.info(
        "dedup_filter: %d件中 %d件通過 (配信済み類似=%d, 記事間類似=%d, 公式=%d)",
        len(articles), len(result),
        delivered_dup_count, inter_dup_count, len(priority),
    )
    return result
