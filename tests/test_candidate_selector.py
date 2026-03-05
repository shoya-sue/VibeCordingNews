#!/usr/bin/env python3
"""candidate_selector モジュールのユニットテスト"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from candidate_selector import _generate_static_summary, select_and_summarize


# ─── _generate_static_summary ───


class TestGenerateStaticSummary:
    def test_html_tags_removed(self):
        raw = "<p>これは<b>重要</b>な記事です</p>"
        result = _generate_static_summary(raw, 120)
        assert "<" not in result
        assert "これは重要な記事です" == result

    def test_html_entities_removed(self):
        raw = "A&amp;B&nbsp;test"
        result = _generate_static_summary(raw, 120)
        assert "&amp;" not in result
        assert "&nbsp;" not in result

    def test_truncation(self):
        raw = "あ" * 200
        result = _generate_static_summary(raw, 120)
        assert len(result) == 121  # 120文字 + "…"
        assert result.endswith("…")

    def test_no_truncation_within_limit(self):
        raw = "短いテキスト"
        result = _generate_static_summary(raw, 120)
        assert result == "短いテキスト"
        assert not result.endswith("…")

    def test_empty_returns_placeholder(self):
        assert _generate_static_summary("", 120) == "（要約なし）"

    def test_whitespace_only_returns_placeholder(self):
        assert _generate_static_summary("   ", 120) == "（要約なし）"

    def test_whitespace_collapsed(self):
        raw = "テスト  文章   です"
        result = _generate_static_summary(raw, 120)
        assert result == "テスト 文章 です"


# ─── select_and_summarize ───


class TestSelectAndSummarize:
    CONFIG = {
        "static_filtering": {
            "max_candidates": 5,
            "max_per_category": 2,
            "summary_max_length": 120,
        }
    }

    def _make_article(self, title, score, category="general", relevance=3):
        return {
            "title": title,
            "composite_score": score,
            "static_relevance": relevance,
            "summary_raw": f"<p>{title}の詳細</p>",
            "category": category,
        }

    def test_selects_top_candidates(self):
        """composite_score上位から選定され、カテゴリが異なれば全件残る"""
        articles = [
            self._make_article("記事A", 5.0, "tech"),
            self._make_article("記事B", 4.0, "science"),
            self._make_article("記事C", 3.0, "general"),
        ]
        result = select_and_summarize(articles, self.CONFIG)
        assert len(result) == 3
        assert result[0]["title"] == "記事A"

    def test_max_candidates_limit(self):
        """max_candidates を超えない"""
        articles = [self._make_article(f"記事{i}", 10 - i) for i in range(10)]
        result = select_and_summarize(articles, self.CONFIG)
        assert len(result) <= 5

    def test_category_diversity(self):
        """同一カテゴリは max_per_category まで"""
        articles = [
            self._make_article("記事A", 5.0, "tech"),
            self._make_article("記事B", 4.0, "tech"),
            self._make_article("記事C", 3.0, "tech"),
            self._make_article("記事D", 2.0, "science"),
        ]
        result = select_and_summarize(articles, self.CONFIG)
        tech_count = sum(1 for a in result if a["category"] == "tech")
        assert tech_count <= 2

    def test_priority_category_unlimited(self):
        """公式ソースはカテゴリ枠制限なし"""
        articles = [
            self._make_article("リリースA", 5.0, "release", 5),
            self._make_article("リリースB", 4.0, "release", 5),
            self._make_article("リリースC", 3.0, "release", 5),
        ]
        result = select_and_summarize(articles, self.CONFIG)
        assert len(result) == 3

    def test_summary_added(self):
        """各記事に summary フィールドが付与される"""
        articles = [self._make_article("テスト", 5.0)]
        result = select_and_summarize(articles, self.CONFIG)
        assert "summary" in result[0]
        assert "<p>" not in result[0]["summary"]

    def test_relevance_field_added(self):
        """各記事に relevance フィールドが付与される"""
        articles = [self._make_article("テスト", 5.0, relevance=4)]
        result = select_and_summarize(articles, self.CONFIG)
        assert result[0]["relevance"] == 4

    def test_fallback_on_empty(self):
        """候補0件時は全記事からcomposite_score最高の1件を補充"""
        # max_per_category=2, category制限で全部弾かれるケースは想定しにくいが
        # 空リスト以外の安全弁テスト
        articles = [self._make_article("唯一の記事", 1.0)]
        result = select_and_summarize(articles, self.CONFIG)
        assert len(result) >= 1

    def test_empty_input(self):
        result = select_and_summarize([], self.CONFIG)
        assert result == []

    def test_priority_before_normal(self):
        """公式ソースは通常記事より先に選定される"""
        articles = [
            self._make_article("通常記事", 10.0, "general"),
            self._make_article("公式リリース", 1.0, "official", 5),
        ]
        result = select_and_summarize(articles, self.CONFIG)
        assert result[0]["category"] == "official"
