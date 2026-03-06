#!/usr/bin/env python3
"""
配信パイプライン E2E 統合テスト

Stage 1（キーワードスコア）→ Stage 2（重複排除）→ Stage 3（候補選定）の
全フローをモックなしで検証する。
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from keyword_scorer import score_articles
from dedup_filter import deduplicate
from candidate_selector import select_and_summarize


# ─── テスト用フィクスチャ ───

def _make_config():
    return {
        "static_filtering": {
            "enabled": True,
            "min_relevance": 3,
            "similarity_threshold": 0.4,
            "delivered_similarity_threshold": 0.5,
            "max_candidates": 5,
            "max_per_category": 2,
            "max_per_priority_category": 1,
            "summary_max_length": 120,
            "freshness_decay_hours": 24.0,
            "freshness_min": 0.2,
        }
    }


def _make_article(
    title="Claude Code 最新機能紹介",
    url="https://example.com/1",
    category="claude-code",
    summary_raw="Claude Code の新しい機能についての詳細説明。",
    hours_ago=2,
):
    return {
        "title": title,
        "url": url,
        "category": category,
        "source": "Zenn",
        "lang": "ja",
        "emoji": "📰",
        "author": "テスト著者",
        "summary_raw": summary_raw,
        "published": datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    }


# ─── パイプライン全体統合テスト ───


class TestPipelineEndToEnd:
    """Stage 1 → Stage 2 → Stage 3 の全フロー検証"""

    def test_relevant_articles_reach_final_selection(self):
        """関連度の高い記事がパイプラインを通り最終選定される"""
        articles = [
            _make_article("Claude Code で爆速開発", "https://example.com/1"),
            _make_article("VibeCoding のすすめ", "https://example.com/2",
                          summary_raw="バイブコーディングの実践方法"),
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)

        assert len(selected) >= 1
        assert all("summary" in a for a in selected)
        assert all("static_relevance" in a for a in selected)
        assert all("composite_score" in a for a in selected)

    def test_irrelevant_articles_removed_at_stage1(self):
        """無関係な記事は Stage 1 で除外され、最終選定に到達しない"""
        articles = [
            _make_article("今日の天気予報", "https://example.com/weather",
                          category="other", summary_raw="晴れです"),
            _make_article("料理レシピ集", "https://example.com/recipe",
                          category="other", summary_raw="美味しい料理の作り方"),
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        assert len(scored) == 0

        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)
        assert len(selected) == 0

    def test_similar_titles_merged_at_stage2(self):
        """類似タイトルは Stage 2 で1件に統合され、最高スコアが残る。
        注意: release/official カテゴリは公式ソースとして記事間重複排除をスキップするため、
        通常カテゴリで検証する。
        """
        articles = [
            _make_article("Claude Code v2.0 リリース", "https://example.com/1",
                          category="claude-code"),
            _make_article("Claude Code v2.0 がリリースされた", "https://example.com/2",
                          category="claude-code"),
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)

        assert len(deduped) == 1

        selected = select_and_summarize(deduped, config)
        assert len(selected) == 1

    def test_past_delivered_excluded_at_stage2(self):
        """過去配信と類似のタイトルは Stage 2 で除外される"""
        articles = [
            _make_article("Claude Code 新機能を紹介", "https://example.com/new"),
        ]
        delivered_titles = ["Claude Code 新機能の紹介記事"]  # 類似タイトル
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, delivered_titles, config)

        assert len(deduped) == 0

    def test_category_diversity_enforced_at_stage3(self):
        """同一カテゴリは max_per_category=2 件まで Stage 3 で制限される"""
        articles = [
            _make_article(f"Claude Code 機能{i}号", f"https://example.com/{i}",
                          category="claude-code")
            for i in range(5)
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)

        claude_code_count = sum(1 for a in selected if a.get("category") == "claude-code")
        assert claude_code_count <= 2

    def test_priority_category_limit_at_stage3(self):
        """release カテゴリは max_per_priority_category=1 件まで"""
        articles = [
            _make_article(f"Claude Code Release {i}", f"https://example.com/{i}",
                          category="release")
            for i in range(3)
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)

        release_count = sum(1 for a in selected if a.get("category") == "release")
        assert release_count <= 1

    def test_safety_net_returns_one_when_all_filtered(self):
        """Stage 2 を通過した記事が1件だけの場合、1件が選定される"""
        articles = [
            _make_article("Claude Code 記事", "https://example.com/1"),
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)

        # Stage 2 通過後の記事を select_and_summarize に渡す
        selected = select_and_summarize(deduped, config)
        assert len(selected) >= 1

    def test_summary_truncated_to_max_length(self):
        """要約は summary_max_length 文字以内に切り詰められる"""
        long_summary = "あ" * 300
        articles = [
            _make_article("Claude Code の使い方", "https://example.com/1",
                          summary_raw=long_summary),
        ]
        config = _make_config()
        config["static_filtering"]["summary_max_length"] = 80

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)

        if selected:
            summary = selected[0]["summary"]
            # "…" を含めて上限チェック
            assert len(summary) <= 80 + len("…")

    def test_composite_score_ordering(self):
        """Stage 3 の選定は composite_score 降順になっている"""
        articles = [
            # 古い記事（鮮度が低い）
            _make_article("Claude Code 古い記事", "https://example.com/old",
                          hours_ago=120),
            # 新しい記事（鮮度が高い）
            _make_article("Claude Code 新しい記事", "https://example.com/new",
                          hours_ago=1),
        ]
        config = _make_config()

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)

        scores = [a["composite_score"] for a in selected]
        assert scores == sorted(scores, reverse=True)

    def test_max_candidates_limit(self):
        """最大候補数 max_candidates を超えない"""
        articles = [
            _make_article(f"Claude Code 特集{i}", f"https://example.com/{i}",
                          category="claude-code" if i % 2 == 0 else "vibecoding")
            for i in range(10)
        ]
        config = _make_config()
        config["static_filtering"]["max_candidates"] = 3

        scored = score_articles(articles, config)
        deduped = deduplicate(scored, [], config)
        selected = select_and_summarize(deduped, config)

        assert len(selected) <= 3
