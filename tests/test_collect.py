"""collect.py のユニットテスト(ネットワーク不使用)。

実行: リポジトリルートで `python -m unittest discover -s tests`
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect


def _entry(title: str, link: str, published: datetime | None, summary: str = "s") -> dict[str, Any]:
    entry: dict[str, Any] = {"title": title, "link": link, "summary": summary}
    if published is not None:
        entry["published_parsed"] = published.utctimetuple()
    return entry


class TestNormalizeText(unittest.TestCase):
    def test_strips_tags_and_unescapes_entities(self) -> None:
        self.assertEqual(
            collect.normalize_text("<p>Hello&nbsp;&amp;<br>world</p>"), "Hello & world"
        )

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(collect.normalize_text("a\n\n  b\tc "), "a b c")

    def test_google_news_style_summary(self) -> None:
        raw = '<ol><li><a href="https://x">記事A&nbsp;&nbsp;媒体A</a></li></ol>'
        self.assertEqual(collect.normalize_text(raw), "記事A 媒体A")


class TestCanonicalUrl(unittest.TestCase):
    def test_strips_tracking_params_only(self) -> None:
        self.assertEqual(
            collect.canonical_url("https://ex.com/a?utm_source=x&id=123&fbclid=z"),
            "https://ex.com/a?id=123",
        )

    def test_keeps_identifying_query(self) -> None:
        self.assertEqual(
            collect.canonical_url("https://www.youtube.com/watch?v=abc&utm_campaign=x"),
            "https://www.youtube.com/watch?v=abc",
        )

    def test_strips_fragment(self) -> None:
        self.assertEqual(collect.canonical_url("https://ex.com/a#section"), "https://ex.com/a")

    def test_id_is_12_hex_and_stable_against_tracking_params(self) -> None:
        with_tracking = collect.entry_item_id("https://ex.com/a?utm_source=x")
        without = collect.entry_item_id("https://ex.com/a")
        self.assertEqual(with_tracking, without)
        self.assertRegex(without, r"^[0-9a-f]{12}$")


class TestCollectCategory(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(collect.JST)
        self.cutoff = self.now - collect.ADOPTION_WINDOW

    def run_category(self, entries_by_feed: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        category = {
            "id": "test",
            "feeds": [{"name": name, "url": f"https://{name}"} for name in entries_by_feed],
        }
        with patch.object(
            collect, "fetch_entries", side_effect=lambda name, url: entries_by_feed[name]
        ):
            return collect.collect_category(category, self.cutoff)

    def test_window_filter_and_undated_adopted_last(self) -> None:
        items = self.run_category(
            {
                "f1": [
                    _entry("old", "https://ex.com/old", self.now - timedelta(hours=30)),
                    _entry("undated", "https://ex.com/undated", None),
                    _entry("new", "https://ex.com/new", self.now - timedelta(hours=1)),
                ]
            }
        )
        self.assertEqual([i["title"] for i in items], ["new", "undated"])
        self.assertIsNone(items[1]["published"])

    def test_dedupe_by_url_and_title_first_wins(self) -> None:
        items = self.run_category(
            {
                "f1": [_entry("t1", "https://ex.com/a?utm_source=rss", self.now)],
                "f2": [
                    _entry("t2", "https://ex.com/a", self.now),  # 同一URL(トラッキング差のみ)
                    _entry("t1", "https://ex.com/other", self.now),  # タイトル完全一致
                    _entry("t3", "https://ex.com/b", self.now),
                ],
            }
        )
        self.assertEqual({i["title"] for i in items}, {"t1", "t3"})
        self.assertEqual(items[0]["source"], "f1")  # 先着優先

    def test_sorted_newest_first_and_capped_at_60(self) -> None:
        entries = [
            _entry(f"t{n}", f"https://ex.com/{n}", self.now - timedelta(minutes=n))
            for n in range(70)
        ]
        items = self.run_category({"f1": entries})
        self.assertEqual(len(items), 60)
        published = [i["published"] for i in items]
        self.assertEqual(published, sorted(published, reverse=True))

    def test_summary_truncated_to_400(self) -> None:
        items = self.run_category(
            {"f1": [_entry("t", "https://ex.com/a", self.now, summary="あ" * 1000)]}
        )
        self.assertEqual(len(items[0]["summary"]), 400)

    def test_skips_entries_without_url_or_title(self) -> None:
        items = self.run_category(
            {
                "f1": [
                    _entry("", "https://ex.com/a", self.now),
                    _entry("t", "", self.now),
                    _entry("ok", "https://ex.com/b", self.now),
                ]
            }
        )
        self.assertEqual([i["title"] for i in items], ["ok"])


class TestMainExitCode(unittest.TestCase):
    FEEDS_YAML = (
        "categories:\n"
        "  - id: c1\n"
        "    feeds:\n"
        "      - { name: f1, url: \"https://example.com/rss\" }\n"
    )

    def run_main(self, entries: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        with tempfile.TemporaryDirectory() as tmp:
            feeds_path = Path(tmp) / "feeds.yaml"
            feeds_path.write_text(self.FEEDS_YAML, encoding="utf-8")
            output_path = Path(tmp) / "data" / "items.json"
            with (
                patch.object(collect, "FEEDS_PATH", feeds_path),
                patch.object(collect, "OUTPUT_PATH", output_path),
                patch.object(collect, "fetch_entries", return_value=entries),
            ):
                code = collect.main()
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        return code, payload

    def test_exit_1_when_all_categories_empty(self) -> None:
        code, payload = self.run_main([])
        self.assertEqual(code, 1)
        self.assertEqual(payload["categories"], [{"id": "c1", "items": []}])

    def test_exit_0_when_any_item_collected(self) -> None:
        code, payload = self.run_main([_entry("t", "https://ex.com/a", datetime.now(collect.JST))])
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["categories"][0]["items"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
