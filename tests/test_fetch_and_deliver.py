#!/usr/bin/env python3
"""fetch_and_deliver モジュールのユニットテスト"""

import csv
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ をインポートパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_and_deliver as fad


# ─── parse_entry_time ───


class TestParseEntryTime:
    def _make_entry(self, published=None, updated=None):
        entry = MagicMock()
        entry.published_parsed = published
        entry.updated_parsed = updated
        return entry

    def test_published_parsed_takes_priority(self):
        pub = (2024, 1, 15, 10, 0, 0, 0, 0, 0)
        upd = (2024, 1, 16, 10, 0, 0, 0, 0, 0)
        entry = self._make_entry(published=pub, updated=upd)
        result = fad.parse_entry_time(entry)
        assert result == datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_falls_back_to_updated_parsed(self):
        upd = (2024, 3, 5, 9, 30, 0, 0, 0, 0)
        entry = self._make_entry(published=None, updated=upd)
        result = fad.parse_entry_time(entry)
        assert result == datetime(2024, 3, 5, 9, 30, 0, tzinfo=timezone.utc)

    def test_returns_now_when_no_time_available(self):
        """published/updated 両方 None の場合は現在時刻（UTC）を返す"""
        entry = self._make_entry(published=None, updated=None)
        before = datetime.now(timezone.utc)
        result = fad.parse_entry_time(entry)
        after = datetime.now(timezone.utc)
        assert before <= result <= after
        assert result.tzinfo == timezone.utc

    def test_invalid_tuple_falls_back_to_updated(self):
        """published_parsed が不正なタプルの場合は updated_parsed を使う"""
        # 不正な値（月が0）を渡してValueError/TypeErrorを起こす
        bad = (2024, 0, 0, 0, 0, 0, 0, 0, 0)
        upd = (2024, 3, 1, 12, 0, 0, 0, 0, 0)
        entry = self._make_entry(published=bad, updated=upd)
        result = fad.parse_entry_time(entry)
        assert result == datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ─── load_delivered / save_delivered ───


class TestDeliveredCsv:
    def _make_article(self, url="https://example.com/1", title="テスト記事"):
        return {
            "url": url,
            "title": title,
            "source": "Zenn",
            "static_relevance": 4,
            "composite_score": 3.5,
            "published": datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        }

    def test_load_delivered_empty_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "delivered.csv"
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                delivered = fad.load_delivered()
            assert delivered == set()
            assert csv_path.exists()

    def test_load_delivered_reads_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "delivered.csv"
            # 先にCSVを作成
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fad.CSV_FIELDNAMES)
                writer.writeheader()
                writer.writerow({
                    "url": "https://example.com/a",
                    "title": "記事A",
                    "source": "Zenn",
                    "delivered_at": "2024-01-15T10:00:00",
                    "static_relevance": "4",
                    "composite_score": "3.5",
                })
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                delivered = fad.load_delivered()
            assert "https://example.com/a" in delivered

    def test_save_delivered_appends_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "delivered.csv"
            # ヘッダー付き空CSVを先に作成
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fad.CSV_FIELDNAMES)
                writer.writeheader()
            article = self._make_article()
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                fad.save_delivered([article])
            with open(csv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == 1
            assert rows[0]["url"] == "https://example.com/1"
            assert rows[0]["title"] == "テスト記事"

    def test_load_delivered_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "delivered.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fad.CSV_FIELDNAMES)
                writer.writeheader()
                for i in range(3):
                    writer.writerow({
                        "url": f"https://example.com/{i}",
                        "title": f"記事タイトル{i}",
                        "source": "Zenn",
                        "delivered_at": "2024-01-15",
                        "static_relevance": "3",
                        "composite_score": "2.0",
                    })
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                titles = fad.load_delivered_titles()
            assert titles == ["記事タイトル0", "記事タイトル1", "記事タイトル2"]

    def test_load_delivered_titles_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "nonexistent.csv"
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                titles = fad.load_delivered_titles()
            assert titles == []


# ─── _migrate_csv_header ───


class TestMigrateCsvHeader:
    def test_no_migration_for_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "delivered.csv"
            csv_path.touch()
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                # 空ファイルはスキップ（例外なし）
                fad._migrate_csv_header()

    def test_no_migration_for_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "nonexistent.csv"
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                fad._migrate_csv_header()

    def test_migration_adds_missing_columns(self):
        """古いCSV（カラム不足）に新カラムを補完する"""
        old_fields = ["url", "title", "source", "delivered_at"]
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "delivered.csv"
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=old_fields)
                writer.writeheader()
                writer.writerow({
                    "url": "https://example.com/old",
                    "title": "古い記事",
                    "source": "Zenn",
                    "delivered_at": "2024-01-01",
                })
            with patch.object(fad, "DELIVERED_CSV", csv_path):
                fad._migrate_csv_header()
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                assert set(fad.CSV_FIELDNAMES) <= set(reader.fieldnames or [])
                rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["url"] == "https://example.com/old"


# ─── get_current_phase ───


class TestGetCurrentPhase:
    def _mock_now(self, hour: int):
        """指定した時刻（JST）でdatetime.nowをモックする"""
        jst = timezone(timedelta(hours=9))
        return datetime(2024, 1, 15, hour, 0, tzinfo=jst)

    def test_early_morning(self):
        with patch("fetch_and_deliver.datetime") as mock_dt:
            mock_dt.now.return_value = self._mock_now(7)
            phase = fad.get_current_phase()
        assert phase["name"] == "early_morning"

    def test_morning(self):
        with patch("fetch_and_deliver.datetime") as mock_dt:
            mock_dt.now.return_value = self._mock_now(10)
            phase = fad.get_current_phase()
        assert phase["name"] == "morning"

    def test_afternoon(self):
        with patch("fetch_and_deliver.datetime") as mock_dt:
            mock_dt.now.return_value = self._mock_now(14)
            phase = fad.get_current_phase()
        assert phase["name"] == "afternoon"

    def test_evening(self):
        with patch("fetch_and_deliver.datetime") as mock_dt:
            mock_dt.now.return_value = self._mock_now(20)
            phase = fad.get_current_phase()
        assert phase["name"] == "evening"

    def test_late_night(self):
        with patch("fetch_and_deliver.datetime") as mock_dt:
            mock_dt.now.return_value = self._mock_now(2)
            phase = fad.get_current_phase()
        assert phase["name"] == "late_night"

    def test_phase_has_required_keys(self):
        with patch("fetch_and_deliver.datetime") as mock_dt:
            mock_dt.now.return_value = self._mock_now(10)
            phase = fad.get_current_phase()
        assert "name" in phase
        assert "tension" in phase
        assert "style" in phase


# ─── send_to_discord ───


class TestSendToDiscord:
    def _make_article(self, title="テスト記事", url="https://example.com/1"):
        return {
            "title": title,
            "url": url,
            "summary": "テスト要約です。",
            "source": "Zenn",
            "author": "テスト著者",
            "category": "ai-agent",
            "emoji": "📰",
            "published": datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            "static_relevance": 4,
            "composite_score": 3.5,
        }

    def _make_config(self):
        return {
            "character": {"name": "VibeちゃんBot"},
            "discord": {"embed_color": 5814783},
        }

    def test_prints_to_stdout_when_no_webhook(self, caplog):
        """DISCORD_WEBHOOK_URL が未設定の場合はstdoutに出力してリターン"""
        with patch.object(fad, "DISCORD_WEBHOOK_URL", ""):
            fad.send_to_discord([self._make_article()], self._make_config())
        # エラーなく終了することを確認

    def test_sends_post_request_to_webhook(self):
        """Webhook URLがある場合はrequests.postを呼ぶ"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch.object(fad, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test"):
            with patch("fetch_and_deliver.requests.post", return_value=mock_resp) as mock_post:
                fad.send_to_discord([self._make_article()], self._make_config())
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert "content" in payload
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1

    def test_embed_title_trimmed_when_too_long(self):
        """256文字超のタイトルはトリムされる"""
        long_title = "あ" * 300
        article = self._make_article(title=long_title)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch.object(fad, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test"):
            with patch("fetch_and_deliver.requests.post", return_value=mock_resp) as mock_post:
                fad.send_to_discord([article], self._make_config())
        payload = mock_post.call_args.kwargs["json"]
        embed_title = payload["embeds"][0]["title"]
        assert len(embed_title) <= fad.DISCORD_EMBED_TITLE_MAX
        assert embed_title.endswith("…")

    def test_embeds_capped_at_ten(self):
        """embedは最大10件に制限される"""
        articles = [self._make_article(title=f"記事{i}", url=f"https://example.com/{i}") for i in range(15)]
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch.object(fad, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test"):
            with patch("fetch_and_deliver.requests.post", return_value=mock_resp) as mock_post:
                fad.send_to_discord(articles, self._make_config())
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["embeds"]) <= fad.DISCORD_EMBEDS_PER_MESSAGE

    def test_version_field_added_when_present(self):
        """versionフィールドがあればembedのfieldsに追加される"""
        article = self._make_article()
        article["version"] = "v2.1.0"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch.object(fad, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test"):
            with patch("fetch_and_deliver.requests.post", return_value=mock_resp) as mock_post:
                fad.send_to_discord([article], self._make_config())
        payload = mock_post.call_args.kwargs["json"]
        field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
        assert "🔖 バージョン" in field_names

    def test_no_version_field_when_absent(self):
        """versionフィールドがなければ🔖フィールドも追加されない"""
        article = self._make_article()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch.object(fad, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test"):
            with patch("fetch_and_deliver.requests.post", return_value=mock_resp) as mock_post:
                fad.send_to_discord([article], self._make_config())
        payload = mock_post.call_args.kwargs["json"]
        field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
        assert "🔖 バージョン" not in field_names
