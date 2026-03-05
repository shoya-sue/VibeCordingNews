#!/usr/bin/env python3
"""dedup_filter モジュールのユニットテスト"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from dedup_filter import _char_bigrams, _jaccard, deduplicate


# ─── _char_bigrams ───


class TestCharBigrams:
    def test_normal_text(self):
        result = _char_bigrams("abc")
        assert result == {"ab", "bc"}

    def test_japanese(self):
        result = _char_bigrams("テスト")
        assert result == {"テス", "スト"}

    def test_ignores_spaces(self):
        result = _char_bigrams("a b c")
        assert result == {"ab", "bc"}

    def test_single_char(self):
        result = _char_bigrams("a")
        assert result == {"a"}

    def test_empty_string(self):
        result = _char_bigrams("")
        assert result == set()

    def test_symbols_removed(self):
        """記号は除去されて連続文字列になる"""
        result = _char_bigrams("a-b.c")
        assert result == {"ab", "bc"}


# ─── _jaccard ───


class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard({"ab", "bc"}, {"ab", "bc"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"ab", "bc"}, {"xy", "yz"}) == 0.0

    def test_partial_overlap(self):
        result = _jaccard({"ab", "bc", "cd"}, {"bc", "cd", "de"})
        # intersection=2, union=4
        assert abs(result - 0.5) < 0.01

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard({"ab"}, set()) == 0.0
        assert _jaccard(set(), {"ab"}) == 0.0


# ─── deduplicate ───


class TestDeduplicate:
    CONFIG = {
        "static_filtering": {
            "similarity_threshold": 0.4,
            "delivered_similarity_threshold": 0.5,
        }
    }

    def _make_article(self, title, score=1.0, category="general"):
        return {
            "title": title,
            "composite_score": score,
            "category": category,
        }

    def test_no_duplicates(self):
        """重複なしの場合、全記事が残る"""
        articles = [
            self._make_article("Claude Codeの新機能", 5.0),
            self._make_article("Pythonの基礎講座", 3.0),
        ]
        result = deduplicate(articles, [], self.CONFIG)
        assert len(result) == 2

    def test_similar_articles_deduped(self):
        """類似タイトルの記事はcomposite_score最高の1件だけ残る"""
        articles = [
            self._make_article("Claude Code新機能リリース", 5.0),
            self._make_article("Claude Code新機能がリリース", 3.0),
        ]
        result = deduplicate(articles, [], self.CONFIG)
        assert len(result) == 1
        assert result[0]["composite_score"] == 5.0

    def test_delivered_title_excluded(self):
        """過去配信済みタイトルと類似する記事は除外"""
        articles = [
            self._make_article("Claude Codeアップデート情報", 5.0),
        ]
        delivered = ["Claude Codeアップデート情報まとめ"]
        result = deduplicate(articles, delivered, self.CONFIG)
        # 類似度が閾値以上なら除外される
        assert len(result) <= 1

    def test_priority_category_bypasses_dedup(self):
        """公式ソース（release/official）は記事間重複排除をスキップ"""
        articles = [
            self._make_article("重要なリリース", 5.0, "release"),
            self._make_article("重要なリリースのお知らせ", 4.0, "release"),
        ]
        result = deduplicate(articles, [], self.CONFIG)
        # 公式ソース同士は重複排除されない
        assert len(result) == 2

    def test_bigrams_field_cleaned(self):
        """一時フィールド _bigrams は結果から除去される"""
        articles = [self._make_article("テスト記事", 1.0)]
        result = deduplicate(articles, [], self.CONFIG)
        for article in result:
            assert "_bigrams" not in article

    def test_empty_input(self):
        result = deduplicate([], [], self.CONFIG)
        assert result == []

    def test_completely_different_titles_preserved(self):
        """全く異なるタイトルは全て残る"""
        articles = [
            self._make_article("AIエージェントの構築方法", 4.0),
            self._make_article("Rustでウェブサーバー", 2.0),
            self._make_article("量子コンピューティング入門", 1.0),
        ]
        result = deduplicate(articles, [], self.CONFIG)
        assert len(result) == 3
