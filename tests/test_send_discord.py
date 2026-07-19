"""send_discord.py のユニットテスト(ネットワーク不使用、requests.post はモック)。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import send_discord

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


def _topic(
    headline: str = "見出し",
    summary: str = "要約",
    importance: int = 4,
    n_sources: int = 1,
    url_prefix: str = "https://ex.com/a",
) -> dict[str, Any]:
    return {
        "headline": headline,
        "summary": summary,
        "importance": importance,
        "deep_dive": False,
        "sources": [
            {"name": f"媒体{n}", "title": f"記事{n}", "url": f"{url_prefix}{n}"}
            for n in range(n_sources)
        ],
    }


def _response(status_code: int = 204, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.headers = headers or {}
    response.text = ""
    response.json.return_value = {}
    return response


class TestBuildEmbed(unittest.TestCase):
    def test_stars_title_url_color_timestamp(self) -> None:
        embed = send_discord.build_embed(_topic(importance=4), 0x5865F2, "2026-07-12T06:30:00+09:00")
        self.assertEqual(embed["title"], "★★★★☆ 見出し")
        self.assertEqual(embed["url"], "https://ex.com/a0")
        self.assertEqual(embed["color"], 0x5865F2)
        self.assertEqual(embed["timestamp"], "2026-07-12T06:30:00+09:00")

    def test_title_truncated_to_256(self) -> None:
        embed = send_discord.build_embed(_topic(headline="あ" * 300), 0, "t")
        self.assertEqual(len(embed["title"]), 256)

    def test_description_summary_blank_line_links_max5(self) -> None:
        embed = send_discord.build_embed(_topic(summary="本文", n_sources=6), 0, "t")
        self.assertTrue(embed["description"].startswith("本文\n\n出典: "))
        self.assertEqual(embed["description"].count("](https://"), 5)

    def test_description_drops_links_over_4096_but_keeps_summary(self) -> None:
        topic = _topic(summary="す" * 300, n_sources=5, url_prefix="https://ex.com/" + "x" * 1500 + "/")
        description = send_discord.build_description(topic)
        self.assertLessEqual(len(description), send_discord.EMBED_DESCRIPTION_MAX)
        self.assertIn("す" * 300, description)

    def test_importance_clamped(self) -> None:
        self.assertEqual(send_discord.importance_stars(7), "★★★★★")
        self.assertEqual(send_discord.importance_stars(0), "★☆☆☆☆")


class TestPackEmbeds(unittest.TestCase):
    def _embed(self, chars: int) -> dict[str, Any]:
        return {"title": "", "description": "x" * chars}

    def test_split_at_10_embeds(self) -> None:
        batches = send_discord.pack_embeds([self._embed(10)] * 11)
        self.assertEqual([len(b) for b in batches], [10, 1])

    def test_split_at_6000_chars(self) -> None:
        batches = send_discord.pack_embeds([self._embed(2900), self._embed(2900), self._embed(300)])
        self.assertEqual([len(b) for b in batches], [2, 1])

    def test_single_batch_when_within_limits(self) -> None:
        batches = send_discord.pack_embeds([self._embed(500)] * 10)
        self.assertEqual([len(b) for b in batches], [10])


class TestSendMessage(unittest.TestCase):
    def test_429_retries_once_after_retry_after(self) -> None:
        responses = [_response(429, {"Retry-After": "2.5"}), _response(204)]
        with (
            patch.object(send_discord.requests, "post", side_effect=responses) as post,
            patch.object(send_discord.time, "sleep") as sleep,
        ):
            send_discord.send_message("https://hook", {"content": "c"})
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(2.5)

    def test_non_429_error_raises(self) -> None:
        with patch.object(send_discord.requests, "post", return_value=_response(400)):
            with self.assertRaises(send_discord.SendFailure):
                send_discord.send_message("https://hook", {"content": "c"})


class TestMain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.feeds_path = Path(self.tmp.name) / "feeds.yaml"
        self.feeds_path.write_text(FEEDS_YAML, encoding="utf-8")
        self.digest_path = Path(self.tmp.name) / "digest.json"
        self.today = datetime.now(send_discord.JST).strftime("%Y-%m-%d")

    def write_digest(self, categories: list[dict[str, Any]], date: str | None = None) -> None:
        payload = {"date": date or self.today, "categories": categories}
        self.digest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def run_main(self, env: dict[str, str], post_responses: list[MagicMock] | None = None) -> tuple[int, MagicMock]:
        responses = post_responses if post_responses is not None else [_response(204)] * 20
        with (
            patch.object(send_discord, "DIGEST_PATH", self.digest_path),
            patch.object(send_discord, "FEEDS_PATH", self.feeds_path),
            patch.object(send_discord.requests, "post", side_effect=responses) as post,
            patch.object(send_discord.time, "sleep"),
            patch.dict(send_discord.os.environ, env, clear=False),
        ):
            for key in ("WEBHOOK_A", "WEBHOOK_B"):
                if key not in env:
                    send_discord.os.environ.pop(key, None)
            code = send_discord.main()
        return code, post

    def test_happy_path_one_message_per_category(self) -> None:
        self.write_digest(
            [
                {"id": "cat_a", "topics": [_topic("a1"), _topic("a2")]},
                {"id": "cat_b", "topics": [_topic("b1")]},
            ]
        )
        code, post = self.run_main({"WEBHOOK_A": "https://hook/a", "WEBHOOK_B": "https://hook/b"})
        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 2)
        payload_a = post.call_args_list[0].kwargs["json"]
        self.assertEqual(payload_a["content"], f"📰 {self.today} ダイジェスト — カテゴリA")
        self.assertEqual(len(payload_a["embeds"]), 2)
        self.assertEqual(post.call_args_list[0].args[0], "https://hook/a")
        self.assertEqual(post.call_args_list[1].args[0], "https://hook/b")

    def test_11_embeds_split_into_two_messages(self) -> None:
        self.write_digest([{"id": "cat_a", "topics": [_topic(f"t{n}") for n in range(11)]}])
        code, post = self.run_main({"WEBHOOK_A": "https://hook/a"})
        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 2)
        contents = [c.kwargs["json"]["content"] for c in post.call_args_list]
        self.assertTrue(contents[0].endswith("(1/2)"))
        self.assertTrue(contents[1].endswith("(2/2)"))
        self.assertEqual(
            [len(c.kwargs["json"]["embeds"]) for c in post.call_args_list], [10, 1]
        )

    def test_over_6000_chars_split_without_trimming_summary(self) -> None:
        long_summary = "長" * 2800
        self.write_digest(
            [{"id": "cat_a", "topics": [_topic(f"t{n}", summary=long_summary) for n in range(3)]}]
        )
        code, post = self.run_main({"WEBHOOK_A": "https://hook/a"})
        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            embeds = call.kwargs["json"]["embeds"]
            total = sum(len(e["title"]) + len(e["description"]) for e in embeds)
            self.assertLessEqual(total, 6000)
            for embed in embeds:
                self.assertIn(long_summary, embed["description"])  # summary は削らない

    def test_stale_date_refuses_to_send(self) -> None:
        yesterday = (datetime.now(send_discord.JST) - timedelta(days=1)).strftime("%Y-%m-%d")
        self.write_digest([{"id": "cat_a", "topics": [_topic()]}], date=yesterday)
        code, post = self.run_main({"WEBHOOK_A": "https://hook/a"})
        self.assertEqual(code, 1)
        self.assertEqual(post.call_count, 0)

    def test_missing_digest_exits_1(self) -> None:
        code, post = self.run_main({"WEBHOOK_A": "https://hook/a"})
        self.assertEqual(code, 1)
        self.assertEqual(post.call_count, 0)

    def test_failed_category_does_not_stop_others(self) -> None:
        self.write_digest(
            [
                {"id": "cat_a", "topics": [_topic("a1")]},
                {"id": "cat_b", "topics": [_topic("b1")]},
            ]
        )
        code, post = self.run_main(
            {"WEBHOOK_A": "https://hook/a", "WEBHOOK_B": "https://hook/b"},
            post_responses=[_response(400), _response(204)],
        )
        self.assertEqual(code, 1)  # 失敗は exit 1 に反映しつつ
        self.assertEqual(post.call_count, 2)  # cat_b の送信は行われる
        self.assertEqual(post.call_args_list[1].args[0], "https://hook/b")

    def test_missing_webhook_env_fails_that_category_only(self) -> None:
        self.write_digest(
            [
                {"id": "cat_a", "topics": [_topic("a1")]},
                {"id": "cat_b", "topics": [_topic("b1")]},
            ]
        )
        code, post = self.run_main({"WEBHOOK_B": "https://hook/b"})
        self.assertEqual(code, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args_list[0].args[0], "https://hook/b")

    def test_empty_category_skipped_silently(self) -> None:
        self.write_digest([{"id": "cat_a", "topics": []}])
        code, post = self.run_main({"WEBHOOK_A": "https://hook/a"})
        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
