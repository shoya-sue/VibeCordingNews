#!/usr/bin/env python3
"""
memory_manager モジュールのユニットテスト

compute_retention / recall_entry / should_review / is_consolidation_candidate
の数学的コア関数を検証する。
"""
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from memory_manager import (
    compute_retention,
    recall_entry,
    should_review,
    is_consolidation_candidate,
    SM2_EF_INITIAL,
    SM2_EF_MIN,
    MEMORY_STRENGTH_INITIAL,
    CONSOLIDATION_MIN_RECALLS,
    CONSOLIDATION_MIN_RETENTION,
    RETENTION_THRESHOLD_ACTIVE,
)

NOW = datetime(2026, 3, 6, 12, 0, 0, tzinfo=timezone.utc)


def _make_entry(
    strength: float = MEMORY_STRENGTH_INITIAL,
    hours_ago: float = 0.0,
    recall_count: int = 0,
    ef: float = SM2_EF_INITIAL,
    interval_days: int = 1,
    layer: int = 2,
    next_review_days_from_now: float = 0.0,
) -> dict:
    last = NOW - timedelta(hours=hours_ago)
    next_review = NOW + timedelta(days=next_review_days_from_now)
    return {
        "last_recalled": last.isoformat(),
        "strength": strength,
        "recall_count": recall_count,
        "ef": ef,
        "interval_days": interval_days,
        "layer": layer,
        "next_review": next_review.isoformat(),
        "retention": 1.0,
    }


# ─── compute_retention ───


class TestComputeRetention:
    def test_immediate_recall_returns_one(self):
        """リコール直後（経過時間0）は保持率 1.0"""
        entry = _make_entry(hours_ago=0)
        r = compute_retention(entry, NOW)
        assert r == pytest.approx(1.0, abs=0.01)

    def test_retention_decreases_over_time(self):
        """時間が経つほど保持率が下がる"""
        r_early = compute_retention(_make_entry(hours_ago=12), NOW)
        r_late = compute_retention(_make_entry(hours_ago=48), NOW)
        assert r_early > r_late

    def test_stronger_memory_decays_slower(self):
        """記憶強度が高いほど保持率の減衰が遅い"""
        entry_weak = _make_entry(strength=0.5, hours_ago=24)
        entry_strong = _make_entry(strength=5.0, hours_ago=24)
        r_weak = compute_retention(entry_weak, NOW)
        r_strong = compute_retention(entry_strong, NOW)
        assert r_strong > r_weak

    def test_retention_formula_matches_expected(self):
        """R(t) = e^(-t/S) の計算が正しい"""
        hours_ago = 24.0
        strength = 2.0
        t_days = hours_ago / 24
        expected = math.exp(-t_days / strength)
        entry = _make_entry(strength=strength, hours_ago=hours_ago)
        r = compute_retention(entry, NOW)
        assert r == pytest.approx(expected, abs=0.001)

    def test_retention_bounded_between_zero_and_one(self):
        """保持率は常に 0.0〜1.0"""
        entry_old = _make_entry(strength=0.1, hours_ago=10000)
        r = compute_retention(entry_old, NOW)
        assert 0.0 <= r <= 1.0

    def test_invalid_date_returns_one(self):
        """不正な日付は保持率 1.0（新しい記憶として扱う）"""
        entry = {"last_recalled": "invalid-date", "strength": 1.0}
        r = compute_retention(entry, NOW)
        assert r == pytest.approx(1.0)

    def test_uses_created_at_when_last_recalled_missing(self):
        """last_recalled がない場合は created_at を使う"""
        entry = {
            "created_at": (NOW - timedelta(hours=24)).isoformat(),
            "strength": 1.0,
        }
        r = compute_retention(entry, NOW)
        expected = math.exp(-1.0 / 1.0)  # t=1日, S=1.0
        assert r == pytest.approx(expected, abs=0.001)


# ─── recall_entry ───


class TestRecallEntry:
    def test_recall_increments_recall_count(self):
        """リコール後は recall_count が 1 増加"""
        entry = _make_entry(recall_count=2)
        updated = recall_entry(entry, quality=4, now=NOW)
        assert updated["recall_count"] == 3

    def test_recall_returns_copy_not_mutated(self):
        """入力エントリを変更せずコピーを返す"""
        entry = _make_entry(recall_count=0)
        original_count = entry["recall_count"]
        recall_entry(entry, quality=4, now=NOW)
        assert entry["recall_count"] == original_count

    def test_retention_is_one_after_recall(self):
        """リコール直後は保持率 1.0"""
        entry = _make_entry(hours_ago=48)
        updated = recall_entry(entry, quality=4, now=NOW)
        assert updated["retention"] == pytest.approx(1.0)

    def test_high_quality_increases_ef(self):
        """品質 5（完璧）は EF を増加させる"""
        entry = _make_entry(ef=SM2_EF_INITIAL)
        updated = recall_entry(entry, quality=5, now=NOW)
        assert updated["ef"] > SM2_EF_INITIAL

    def test_low_quality_decreases_ef(self):
        """品質 0（全く覚えていない）は EF を減少させる"""
        entry = _make_entry(ef=SM2_EF_INITIAL)
        updated = recall_entry(entry, quality=0, now=NOW)
        assert updated["ef"] < SM2_EF_INITIAL

    def test_ef_never_goes_below_minimum(self):
        """EF は SM2_EF_MIN (1.3) 以下にならない"""
        entry = _make_entry(ef=SM2_EF_MIN)
        # 品質0で繰り返しリコールしても最小値を下回らない
        updated = recall_entry(entry, quality=0, now=NOW)
        assert updated["ef"] >= SM2_EF_MIN

    def test_quality_clamped_to_0_5(self):
        """品質値は 0〜5 にクランプされる"""
        entry = _make_entry()
        # 範囲外の値でも例外を出さない
        updated_high = recall_entry(entry, quality=10, now=NOW)
        updated_low = recall_entry(entry, quality=-1, now=NOW)
        assert 0 <= updated_high["ef"]
        assert 0 <= updated_low["ef"]

    def test_strength_increases_on_good_recall(self):
        """品質 4 以上のリコールは記憶強度を増加させる"""
        entry = _make_entry(strength=MEMORY_STRENGTH_INITIAL)
        updated = recall_entry(entry, quality=4, now=NOW)
        assert updated["strength"] > MEMORY_STRENGTH_INITIAL

    def test_interval_is_1_on_first_recall(self):
        """初回リコールのインターバルは 1 日"""
        entry = _make_entry(recall_count=0)
        updated = recall_entry(entry, quality=4, now=NOW)
        assert updated["interval_days"] == 1

    def test_interval_is_6_on_second_recall(self):
        """2回目リコールのインターバルは 6 日"""
        entry = _make_entry(recall_count=1)
        updated = recall_entry(entry, quality=4, now=NOW)
        assert updated["interval_days"] == 6

    def test_interval_grows_after_multiple_recalls(self):
        """3回目以降は前回インターバル × EF でインターバルが伸びる"""
        entry = _make_entry(recall_count=2, interval_days=6, ef=SM2_EF_INITIAL)
        updated = recall_entry(entry, quality=4, now=NOW)
        # I = round(6 * EF') >= 6
        assert updated["interval_days"] >= 6


# ─── should_review ───


class TestShouldReview:
    def test_past_next_review_needs_review(self):
        """next_review を過ぎたエントリはレビュー必要"""
        entry = _make_entry(
            next_review_days_from_now=-1,  # 昨日
            hours_ago=0,  # リコールは今日（保持率高い）
            strength=100.0,  # 強度を高くして保持率でフィルタされないようにする
        )
        assert should_review(entry, NOW) is True

    def test_low_retention_needs_review(self):
        """保持率が閾値 (0.7) を下回るとレビュー必要"""
        # 保持率が低くなるよう強度を低く、経過時間を長くする
        entry = _make_entry(strength=0.5, hours_ago=36, next_review_days_from_now=10)
        r = compute_retention(entry, NOW)
        # 保持率が閾値以下かどうかを検証してからテスト
        if r < RETENTION_THRESHOLD_ACTIVE:
            assert should_review(entry, NOW) is True

    def test_fresh_memory_no_review_needed(self):
        """リコール直後かつ next_review が未来なら不要"""
        entry = _make_entry(
            strength=10.0,
            hours_ago=0,
            next_review_days_from_now=7,
        )
        # 保持率高い（>0.7）かつ next_review 未来 → False
        assert should_review(entry, NOW) is False


# ─── is_consolidation_candidate ───


class TestIsConsolidationCandidate:
    def test_not_candidate_when_layer_3(self):
        """既に Layer 3 のエントリは統合候補外"""
        entry = _make_entry(
            layer=3,
            recall_count=CONSOLIDATION_MIN_RECALLS,
            strength=5.0,
            hours_ago=0,
        )
        assert is_consolidation_candidate(entry, NOW) is False

    def test_not_candidate_when_recall_count_insufficient(self):
        """リコール回数が不足していると候補外"""
        entry = _make_entry(
            layer=2,
            recall_count=CONSOLIDATION_MIN_RECALLS - 1,
            strength=5.0,
            hours_ago=0,
        )
        assert is_consolidation_candidate(entry, NOW) is False

    def test_not_candidate_when_retention_too_low(self):
        """保持率が低いと候補外"""
        # 強度を低く、経過時間を長くして保持率を 0.5 未満にする
        entry = _make_entry(
            layer=2,
            recall_count=CONSOLIDATION_MIN_RECALLS,
            strength=0.3,
            hours_ago=72,
        )
        r = compute_retention(entry, NOW)
        if r < CONSOLIDATION_MIN_RETENTION:
            assert is_consolidation_candidate(entry, NOW) is False

    def test_is_candidate_when_all_conditions_met(self):
        """全条件を満たすと統合候補になる"""
        entry = _make_entry(
            layer=2,
            recall_count=CONSOLIDATION_MIN_RECALLS,
            strength=10.0,   # 保持率を高く保つ
            hours_ago=1,     # ほぼ今リコールした
        )
        r = compute_retention(entry, NOW)
        # 保持率 >= 0.5 かつ recall_count >= 5 かつ layer == 2
        assert r >= CONSOLIDATION_MIN_RETENTION
        assert is_consolidation_candidate(entry, NOW) is True
