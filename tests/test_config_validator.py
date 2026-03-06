#!/usr/bin/env python3
"""config_validator モジュールのユニットテスト"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from config_validator import validate_config, ConfigValidationError


def _minimal_config() -> dict:
    """バリデーションが通る最小限の設定"""
    return {
        "feeds": [
            {"name": "Test Feed", "url": "https://example.com/feed", "category": "claude-code", "lang": "ja", "emoji": "📰"}
        ],
        "discord": {
            "max_items_per_delivery": 5,
            "embed_color": 5814783,
        },
        "rate_limits": {
            "gemini_daily_max": 50,
        },
    }


# ─── 正常系 ───


class TestValidConfigPasses:
    def test_minimal_config(self):
        """必須フィールドのみの最小設定は通過する"""
        validate_config(_minimal_config())

    def test_with_static_filtering(self):
        """static_filteringセクション付きは通過する"""
        config = _minimal_config()
        config["static_filtering"] = {
            "enabled": True,
            "min_relevance": 3,
            "max_candidates": 5,
            "max_per_category": 2,
            "summary_max_length": 120,
            "freshness_decay_hours": 24.0,
            "freshness_min": 0.2,
        }
        validate_config(config)

    def test_static_filtering_without_optional_freshness(self):
        """freshness_* は省略可能"""
        config = _minimal_config()
        config["static_filtering"] = {
            "enabled": True,
            "min_relevance": 3,
            "max_candidates": 5,
            "max_per_category": 2,
            "summary_max_length": 120,
        }
        validate_config(config)

    def test_multiple_feeds(self):
        """複数フィードは通過する"""
        config = _minimal_config()
        config["feeds"].append(
            {"name": "Feed2", "url": "https://example.com/2", "category": "release", "lang": "en", "emoji": "🚀"}
        )
        validate_config(config)


# ─── 必須セクション欠落 ───


class TestMissingRequiredSections:
    def test_missing_feeds(self):
        config = _minimal_config()
        del config["feeds"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("feeds" in e for e in exc.value.errors)

    def test_missing_discord(self):
        config = _minimal_config()
        del config["discord"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("discord" in e for e in exc.value.errors)

    def test_missing_rate_limits(self):
        config = _minimal_config()
        del config["rate_limits"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("rate_limits" in e for e in exc.value.errors)


# ─── feeds バリデーション ───


class TestFeedsValidation:
    def test_empty_feeds_list(self):
        config = _minimal_config()
        config["feeds"] = []
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("1件以上" in e for e in exc.value.errors)

    def test_feed_missing_name(self):
        config = _minimal_config()
        config["feeds"][0] = {"url": "https://example.com", "category": "claude-code", "lang": "ja", "emoji": "📰"}
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("name" in e for e in exc.value.errors)

    def test_feed_missing_url(self):
        config = _minimal_config()
        config["feeds"][0] = {"name": "Test", "category": "claude-code", "lang": "ja", "emoji": "📰"}
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("url" in e for e in exc.value.errors)

    def test_feeds_not_list(self):
        config = _minimal_config()
        config["feeds"] = "not a list"
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("feeds" in e for e in exc.value.errors)


# ─── static_filtering バリデーション ───


class TestStaticFilteringValidation:
    def test_min_relevance_out_of_range(self):
        config = _minimal_config()
        config["static_filtering"] = {
            "enabled": True,
            "min_relevance": 10,  # 範囲外（1-5）
            "max_candidates": 5,
            "max_per_category": 2,
            "summary_max_length": 120,
        }
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("min_relevance" in e for e in exc.value.errors)

    def test_max_candidates_wrong_type(self):
        config = _minimal_config()
        config["static_filtering"] = {
            "enabled": True,
            "min_relevance": 3,
            "max_candidates": "five",  # 型が違う
            "max_per_category": 2,
            "summary_max_length": 120,
        }
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("max_candidates" in e for e in exc.value.errors)

    def test_freshness_decay_hours_out_of_range(self):
        config = _minimal_config()
        config["static_filtering"] = {
            "enabled": True,
            "min_relevance": 3,
            "max_candidates": 5,
            "max_per_category": 2,
            "summary_max_length": 120,
            "freshness_decay_hours": 0.1,  # 範囲外（1.0-168.0）
        }
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("freshness_decay_hours" in e for e in exc.value.errors)

    def test_freshness_min_out_of_range(self):
        config = _minimal_config()
        config["static_filtering"] = {
            "enabled": True,
            "min_relevance": 3,
            "max_candidates": 5,
            "max_per_category": 2,
            "summary_max_length": 120,
            "freshness_min": 1.5,  # 範囲外（0.0-1.0）
        }
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("freshness_min" in e for e in exc.value.errors)


# ─── discord バリデーション ───


class TestDiscordValidation:
    def test_max_items_out_of_range(self):
        config = _minimal_config()
        config["discord"]["max_items_per_delivery"] = 20  # 範囲外（1-10）
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("max_items_per_delivery" in e for e in exc.value.errors)

    def test_embed_color_wrong_type(self):
        config = _minimal_config()
        config["discord"]["embed_color"] = "blue"
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert any("embed_color" in e for e in exc.value.errors)


# ─── ConfigValidationError の形式 ───


class TestConfigValidationError:
    def test_error_message_contains_all_issues(self):
        """複数エラーをまとめて報告する"""
        config = _minimal_config()
        del config["feeds"]
        del config["discord"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_config(config)
        assert len(exc.value.errors) >= 2

    def test_error_is_value_error_subclass(self):
        config = _minimal_config()
        del config["feeds"]
        with pytest.raises(ValueError):
            validate_config(config)
