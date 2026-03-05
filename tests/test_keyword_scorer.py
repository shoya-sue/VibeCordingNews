#!/usr/bin/env python3
"""keyword_scorer モジュールのユニットテスト"""

import sys
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# scripts/ をインポートパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from keyword_scorer import (
    _normalize,
    _match_tier,
    _calc_freshness,
    _is_title_valid,
    _has_code_block,
    score_articles,
    KEYWORD_TIERS,
    SOURCE_RELEVANCE_FLOOR,
    SOURCE_WEIGHTS,
    TITLE_MATCH_BONUS,
    CODE_BLOCK_BONUS,
)


# ─── _normalize ───


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("Claude Code") == "claude code"

    def test_fullwidth_to_halfwidth(self):
        assert _normalize("Ｃｌａｕｄｅ") == "claude"
        assert _normalize("０１２３") == "0123"

    def test_whitespace_collapse(self):
        assert _normalize("claude   code  test") == "claude code test"

    def test_strip(self):
        assert _normalize("  claude  ") == "claude"

    def test_empty(self):
        assert _normalize("") == ""


# ─── _match_tier ───


class TestMatchTier:
    # Tier 5: 最高優先キーワード
    def test_tier5_claude_code(self):
        assert _match_tier("Claude Code最新アップデート") == 5

    def test_tier5_vibecoding(self):
        assert _match_tier("VibeCodingの始め方") == 5

    def test_tier5_vibe_coding_space(self):
        assert _match_tier("Vibe Codingとは") == 5

    def test_tier5_katakana(self):
        assert _match_tier("バイブコーディング入門") == 5

    # Tier 4: Anthropic関連
    def test_tier4_claude(self):
        assert _match_tier("Claudeの新機能") == 4

    def test_tier4_anthropic(self):
        assert _match_tier("Anthropic社の発表") == 4

    def test_tier4_mcp_word_boundary(self):
        """MCPは単語境界マッチ — 'MCPサーバー' でマッチする"""
        assert _match_tier("MCPサーバーの構築") == 4

    def test_tier4_ai_agent(self):
        assert _match_tier("AI Agentの活用法") == 4

    def test_tier4_agentic(self):
        assert _match_tier("Agentic AIの未来") == 4

    # Tier 3: AI開発ツール
    def test_tier3_copilot(self):
        assert _match_tier("GitHub Copilotレビュー") == 3

    def test_tier3_cursor(self):
        assert _match_tier("Cursor IDEの使い方") == 3

    def test_tier3_llm_word_boundary(self):
        assert _match_tier("LLMの最新動向") == 3

    def test_tier3_rag_word_boundary(self):
        assert _match_tier("RAGパイプライン構築") == 3

    # Tier 2: 一般AI
    def test_tier2_ai_word_boundary(self):
        assert _match_tier("AI技術の進化") == 2

    def test_tier2_chatgpt(self):
        assert _match_tier("ChatGPTの活用") == 2

    def test_tier2_generative_ai(self):
        assert _match_tier("生成AIの可能性") == 2

    # Tier 1: マッチなし
    def test_tier1_no_match(self):
        assert _match_tier("Pythonでウェブスクレイピング") == 1

    def test_tier1_empty(self):
        assert _match_tier("") == 1

    # 単語境界の誤検知防止
    def test_ai_no_false_positive_in_wait(self):
        """'ai' が 'wait' に部分一致しないことを確認"""
        assert _match_tier("Please wait for the result") == 1

    def test_ai_no_false_positive_in_domain(self):
        assert _match_tier("domain driven design") == 1

    def test_ai_no_false_positive_in_explain(self):
        assert _match_tier("How to explain this concept") == 1

    # 最高ティアが採用される
    def test_highest_tier_wins(self):
        """複数ティアにマッチする場合、最高ティアが返る"""
        assert _match_tier("Claude Codeで作るAI Agent") == 5


# ─── _calc_freshness ───


class TestCalcFreshness:
    def test_none_returns_half(self):
        assert _calc_freshness(None) == 0.5

    def test_just_published(self):
        now = datetime.now(timezone.utc)
        result = _calc_freshness(now)
        assert result > 0.99

    def test_24h_ago(self):
        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        result = _calc_freshness(yesterday)
        expected = math.exp(-1)
        assert abs(result - expected) < 0.05

    def test_very_old_returns_floor(self):
        """非常に古い記事は下限0.2を返す"""
        old = datetime.now(timezone.utc) - timedelta(days=30)
        assert _calc_freshness(old) == 0.2

    def test_naive_datetime_treated_as_utc(self):
        """tzinfo=None の naive datetime は UTC として扱う"""
        now_naive = datetime.utcnow()
        result = _calc_freshness(now_naive)
        assert result > 0.99


# ─── score_articles ───


class TestScoreArticles:
    CONFIG = {"static_filtering": {"min_relevance": 3}}

    def test_high_relevance_passes(self):
        articles = [
            {"title": "Claude Codeの新機能", "summary_raw": "", "category": "claude-code"}
        ]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 1
        assert result[0]["static_relevance"] == 5

    def test_low_relevance_filtered(self):
        """min_relevance=3 未満の記事は除外される"""
        articles = [
            {"title": "Pythonの基礎", "summary_raw": "変数と関数", "category": "general"}
        ]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 0

    def test_source_floor_guarantees_passage(self):
        """キーワード不一致でもソースカテゴリFloorでmin_relevance以上になる"""
        articles = [
            {"title": "New release notes", "summary_raw": "Bug fixes", "category": "release"}
        ]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 1
        assert result[0]["static_relevance"] == 5

    def test_ai_agent_floor(self):
        """ai-agentカテゴリはfloor=3で通過保証"""
        articles = [
            {"title": "Mastra Announcements", "summary_raw": "", "category": "ai-agent"}
        ]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 1
        assert result[0]["static_relevance"] >= 3

    def test_title_match_bonus(self):
        """タイトルにキーワードがある場合、composite_scoreにボーナスが乗る"""
        articles_title = [
            {"title": "Claude活用ガイド", "summary_raw": "", "category": "general"}
        ]
        articles_body = [
            {"title": "ツール紹介", "summary_raw": "Claudeは便利です", "category": "general"}
        ]
        result_title = score_articles(articles_title, self.CONFIG)
        result_body = score_articles(articles_body, self.CONFIG)
        assert len(result_title) == 1
        assert len(result_body) == 1
        # タイトルマッチの方がcomposite_scoreが高い
        assert result_title[0]["composite_score"] > result_body[0]["composite_score"]

    def test_source_weight_applied(self):
        """ソースカテゴリ重みがcomposite_scoreに反映される"""
        base = [{"title": "Claude新機能", "summary_raw": "", "category": "general"}]
        weighted = [{"title": "Claude新機能", "summary_raw": "", "category": "official"}]
        r_base = score_articles(base, self.CONFIG)
        r_weighted = score_articles(weighted, self.CONFIG)
        assert r_weighted[0]["composite_score"] > r_base[0]["composite_score"]

    def test_sorted_by_composite_score_desc(self):
        """結果はcomposite_score降順でソートされる"""
        articles = [
            {"title": "AI開発の基礎", "summary_raw": "", "category": "general"},
            {"title": "Claude Codeリリース", "summary_raw": "", "category": "release"},
        ]
        result = score_articles(articles, self.CONFIG)
        assert len(result) >= 1
        for i in range(len(result) - 1):
            assert result[i]["composite_score"] >= result[i + 1]["composite_score"]

    def test_composite_score_fields_added(self):
        """static_relevance と composite_score がdictに付与される"""
        articles = [{"title": "Anthropicの発表", "summary_raw": "", "category": "general"}]
        result = score_articles(articles, self.CONFIG)
        assert "static_relevance" in result[0]
        assert "composite_score" in result[0]


# ─── タイトル品質フィルタ ───


class TestTitleFilter:
    CONFIG = {"static_filtering": {"min_relevance": 1}}  # relevanceで弾かれないよう最低値

    def test_short_title_filtered(self):
        """5文字未満のタイトルは除外"""
        articles = [{"title": "短い", "summary_raw": "", "category": "general"}]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 0

    def test_version_only_filtered(self):
        """バージョン番号のみのタイトルは除外（通常カテゴリ）"""
        articles = [{"title": "v2.1.69", "summary_raw": "", "category": "general"}]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 0

    def test_version_only_release_not_filtered(self):
        """releaseカテゴリはタイトルがバージョン番号のみでも除外しない"""
        articles = [{"title": "v2.1.69", "summary_raw": "", "category": "release"}]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 1

    def test_no_word_chars_filtered(self):
        """日本語・英字を一切含まないタイトルは除外"""
        articles = [{"title": "12345678", "summary_raw": "", "category": "general"}]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 0

    def test_valid_title_passes(self):
        """正常なタイトルは通過する"""
        articles = [{"title": "Claude Code v2.1.69 リリース", "summary_raw": "", "category": "release"}]
        result = score_articles(articles, self.CONFIG)
        assert len(result) == 1

    def test_is_title_valid_short(self):
        assert _is_title_valid("短い") == (False, "タイトルが短すぎる: 2文字")

    def test_is_title_valid_version_only(self):
        valid, reason = _is_title_valid("v2.1.69")
        assert not valid
        assert "バージョン番号のみ" in reason

    def test_is_title_valid_normal(self):
        assert _is_title_valid("Claude Codeの最新機能") == (True, "")


# ─── コードブロック検出 ───


class TestCodeBlockBonus:
    CONFIG = {"static_filtering": {"min_relevance": 3}}

    def test_backtick_code_block_detected(self):
        assert _has_code_block("```python\nprint('hello')\n```") is True

    def test_html_code_tag_detected(self):
        assert _has_code_block("<code>snippet</code>") is True

    def test_no_code_block(self):
        assert _has_code_block("テキストのみの記事") is False

    def test_empty_summary(self):
        assert _has_code_block("") is False

    def test_code_block_increases_score(self):
        """コードブロックありの記事はなしより composite_score が高い"""
        with_code = [{"title": "Claude活用ガイド", "summary_raw": "```python\ncode\n```", "category": "general"}]
        without_code = [{"title": "Claude活用ガイド", "summary_raw": "テキストのみ", "category": "general"}]
        r_with = score_articles(with_code, self.CONFIG)
        r_without = score_articles(without_code, self.CONFIG)
        assert len(r_with) == 1
        assert len(r_without) == 1
        assert r_with[0]["composite_score"] > r_without[0]["composite_score"]

    def test_code_block_bonus_value(self):
        """CODE_BLOCK_BONUS は 0 より大きい定数"""
        assert CODE_BLOCK_BONUS > 0
