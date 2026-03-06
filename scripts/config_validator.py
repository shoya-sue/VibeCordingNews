#!/usr/bin/env python3
"""
config.json バリデーター — 標準ライブラリのみで構成の整合性を検証する。

起動時に load_config() 直後に呼び出すことで、
設定値の欠落や型誤りを早期に検出できる。
"""

from __future__ import annotations

from typing import Any


# バリデーションエラーをまとめて報告するための例外
class ConfigValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(f"  - {e}" for e in errors))


def _check_type(path: str, value: Any, expected: type, errors: list[str]):
    if not isinstance(value, expected):
        errors.append(f"{path}: {expected.__name__} が必要ですが {type(value).__name__} です")


def _check_range(path: str, value: Any, min_val: float, max_val: float, errors: list[str]):
    if isinstance(value, (int, float)) and not (min_val <= value <= max_val):
        errors.append(f"{path}: {min_val}〜{max_val} の範囲が必要ですが {value} です")


def _validate_feeds(feeds: Any, errors: list[str]):
    if not isinstance(feeds, list):
        errors.append("feeds: list が必要です")
        return
    if len(feeds) == 0:
        errors.append("feeds: 1件以上のフィードが必要です")
        return
    required_feed_keys = {"name", "url", "category", "lang", "emoji"}
    for i, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            errors.append(f"feeds[{i}]: dict が必要です")
            continue
        for key in required_feed_keys:
            if key not in feed:
                errors.append(f"feeds[{i}]: '{key}' が必要です")
            elif not isinstance(feed[key], str):
                errors.append(f"feeds[{i}].{key}: str が必要です")


def _validate_static_filtering(sf: Any, errors: list[str]):
    if not isinstance(sf, dict):
        errors.append("static_filtering: dict が必要です")
        return
    _check_type("static_filtering.enabled", sf.get("enabled"), bool, errors)
    _check_type("static_filtering.min_relevance", sf.get("min_relevance"), int, errors)
    _check_range("static_filtering.min_relevance", sf.get("min_relevance", 3), 1, 5, errors)
    _check_type("static_filtering.max_candidates", sf.get("max_candidates"), int, errors)
    _check_range("static_filtering.max_candidates", sf.get("max_candidates", 5), 1, 20, errors)
    _check_type("static_filtering.max_per_category", sf.get("max_per_category"), int, errors)
    _check_range("static_filtering.max_per_category", sf.get("max_per_category", 2), 1, 10, errors)
    _check_type("static_filtering.summary_max_length", sf.get("summary_max_length"), int, errors)
    _check_range("static_filtering.summary_max_length", sf.get("summary_max_length", 120), 50, 500, errors)

    # freshness 係数（float は int でも許容）
    decay = sf.get("freshness_decay_hours")
    if decay is not None and not isinstance(decay, (int, float)):
        errors.append("static_filtering.freshness_decay_hours: number が必要です")
    elif decay is not None:
        _check_range("static_filtering.freshness_decay_hours", decay, 1.0, 168.0, errors)

    min_fresh = sf.get("freshness_min")
    if min_fresh is not None and not isinstance(min_fresh, (int, float)):
        errors.append("static_filtering.freshness_min: number が必要です")
    elif min_fresh is not None:
        _check_range("static_filtering.freshness_min", min_fresh, 0.0, 1.0, errors)


def _validate_discord(discord: Any, errors: list[str]):
    if not isinstance(discord, dict):
        errors.append("discord: dict が必要です")
        return
    _check_type("discord.max_items_per_delivery", discord.get("max_items_per_delivery"), int, errors)
    _check_range("discord.max_items_per_delivery", discord.get("max_items_per_delivery", 5), 1, 10, errors)
    _check_type("discord.embed_color", discord.get("embed_color"), int, errors)


def _validate_rate_limits(rl: Any, errors: list[str]):
    if not isinstance(rl, dict):
        errors.append("rate_limits: dict が必要です")
        return
    _check_type("rate_limits.gemini_daily_max", rl.get("gemini_daily_max"), int, errors)
    _check_range("rate_limits.gemini_daily_max", rl.get("gemini_daily_max", 50), 0, 10000, errors)


def validate_config(config: dict) -> None:
    """config.json の必須フィールドと型・範囲を検証する。

    問題があれば ConfigValidationError を送出する。
    正常時は何も返さない。

    Args:
        config: load_config() で読み込んだ設定 dict
    """
    errors: list[str] = []

    # 最上位の必須セクション
    for section in ("feeds", "discord", "rate_limits"):
        if section not in config:
            errors.append(f"'{section}' セクションが必要です")

    # 各セクションの詳細バリデーション
    _validate_feeds(config.get("feeds"), errors)

    if "static_filtering" in config:
        _validate_static_filtering(config["static_filtering"], errors)

    if "discord" in config:
        _validate_discord(config["discord"], errors)

    if "rate_limits" in config:
        _validate_rate_limits(config["rate_limits"], errors)

    if errors:
        raise ConfigValidationError(errors)
