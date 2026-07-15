"""render_md.py のユニットテスト(ネットワーク不使用)。"""
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
import render_md

FEEDS_YAML = """\
categories:
  - id: cat_a
    name: "カテゴリA"
    webhook_env: WEBHOOK_A
    color: 0x111111
    max_topics: 4
    feeds: []
  - id: cat_b
    name: "カテゴリB"
    webhook_env: WEBHOOK_B
    color: 0x222222
    max_topics: 3
    feeds: []
"""


def _topic(headline: str = "見出し", importance: int = 4, n_sources: int = 1) -> dict[str, Any]:
    return {
        "headline": headline,
        "summary": "要約本文",
        "importance": importance,
        "deep_dive": False,
        "sources": [
            {"name": f"媒体{n}", "title": f"記事{n}", "url": f"https://ex.com/{n}"}
            for n in range(n_sources)
        ],
    }


class TestRendering(unittest.TestCase):
    def test_topic_format_follows_spec(self) -> None:
        text = render_md.render_topic(_topic(n_sources=2))
        self.assertEqual(
            text,
            "### ★★★★☆ 見出し\n要約本文\n\n出典: [媒体0](https://ex.com/0) / [媒体1](https://ex.com/1)\n",
        )

    def test_sources_capped_at_5(self) -> None:
        text = render_md.render_topic(_topic(n_sources=7))
        self.assertEqual(text.count("](https://"), 5)

    def test_digest_md_skips_empty_category_and_maps_names(self) -> None:
        digest = {
            "date": "2026-07-15",
            "categories": [
                {"id": "cat_a", "topics": [_topic("a1"), _topic("a2", importance=5)]},
                {"id": "cat_b", "topics": []},
            ],
        }
        text = render_md.render_digest_md(digest, {"cat_a": "カテゴリA", "cat_b": "カテゴリB"})
        self.assertIn("# 📰 2026-07-15 ダイジェスト\n", text)
        self.assertIn("## カテゴリA\n", text)
        self.assertNotIn("カテゴリB", text)
        self.assertIn("### ★★★★★ a2\n", text)

    def test_readme_lists_latest_first_max_7(self) -> None:
        dates = [f"2026-07-{day:02d}" for day in range(15, 5, -1)]  # 10日分・降順
        text = render_md.render_readme(dates)
        self.assertIn("最新: [2026-07-15](digest/2026-07-15.md)", text)
        self.assertEqual(text.count("- ["), 7)
        self.assertNotIn("2026-07-07", text)

    def test_readme_without_digests(self) -> None:
        text = render_md.render_readme([])
        self.assertIn("最新: (まだダイジェストはありません)", text)


class TestMain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.digest_path = root / "data" / "digest.json"
        self.digest_path.parent.mkdir()
        self.feeds_path = root / "feeds.yaml"
        self.feeds_path.write_text(FEEDS_YAML, encoding="utf-8")
        self.digest_dir = root / "digest"
        self.archive_dir = root / "data" / "archive"
        self.readme_path = root / "README.md"
        self.today = datetime.now(render_md.JST).strftime("%Y-%m-%d")

    def write_digest(self, date: str | None = None) -> None:
        payload = {
            "date": date or self.today,
            "categories": [{"id": "cat_a", "topics": [_topic()]}],
        }
        self.digest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def run_main(self) -> int:
        with (
            patch.object(render_md, "DIGEST_PATH", self.digest_path),
            patch.object(render_md, "FEEDS_PATH", self.feeds_path),
            patch.object(render_md, "DIGEST_DIR", self.digest_dir),
            patch.object(render_md, "ARCHIVE_DIR", self.archive_dir),
            patch.object(render_md, "README_PATH", self.readme_path),
        ):
            return render_md.main()

    def test_happy_path_writes_all_three_outputs(self) -> None:
        self.write_digest()
        self.assertEqual(self.run_main(), 0)

        md = (self.digest_dir / f"{self.today}.md").read_text(encoding="utf-8")
        self.assertIn(f"# 📰 {self.today} ダイジェスト", md)
        self.assertIn("## カテゴリA", md)

        readme = self.readme_path.read_text(encoding="utf-8")
        self.assertIn(f"最新: [{self.today}](digest/{self.today}.md)", readme)

        archived = json.loads(
            (self.archive_dir / f"{self.today}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(archived["date"], self.today)
        self.assertTrue(self.digest_path.exists())  # コピーであって移動ではない

    def test_readme_reflects_existing_older_digests(self) -> None:
        self.digest_dir.mkdir()
        (self.digest_dir / "2000-01-01.md").write_text("old", encoding="utf-8")
        (self.digest_dir / "note.txt").write_text("ignore", encoding="utf-8")
        self.write_digest()
        self.assertEqual(self.run_main(), 0)
        readme = self.readme_path.read_text(encoding="utf-8")
        self.assertIn(f"最新: [{self.today}]", readme)
        self.assertIn("- [2000-01-01](digest/2000-01-01.md)", readme)
        self.assertNotIn("note", readme)

    def test_stale_date_refuses_and_writes_nothing(self) -> None:
        yesterday = (datetime.now(render_md.JST) - timedelta(days=1)).strftime("%Y-%m-%d")
        self.write_digest(date=yesterday)
        self.assertEqual(self.run_main(), 1)
        self.assertFalse(self.digest_dir.exists())
        self.assertFalse(self.readme_path.exists())
        self.assertFalse(self.archive_dir.exists())

    def test_missing_digest_exits_1(self) -> None:
        self.assertEqual(self.run_main(), 1)

    def test_rerun_same_day_is_idempotent(self) -> None:
        self.write_digest()
        self.assertEqual(self.run_main(), 0)
        first = (self.digest_dir / f"{self.today}.md").read_text(encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        second = (self.digest_dir / f"{self.today}.md").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        readme = self.readme_path.read_text(encoding="utf-8")
        self.assertEqual(readme.count(f"- [{self.today}]"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
