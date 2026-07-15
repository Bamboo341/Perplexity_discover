"""send_discord.py — sink A: data/digest.json を Discord webhook へカード(embed)形式で送信する。

- 入力は data/digest.json と .env の webhook URL 群(読み取り専用。ファイルの移動・削除はしない)
- digest.json の date が当日(JST)でなければ送信せず exit 1(前日分の再配信防止。Digest_spec.md §6)
- カテゴリ単位で送信し、あるカテゴリの失敗は他カテゴリの送信を止めない(最後に exit 1 を返す)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv

JST = timezone(timedelta(hours=9))
DIGEST_PATH = Path("data/digest.json")
FEEDS_PATH = Path("feeds.yaml")
MAX_EMBEDS_PER_MESSAGE = 10
MAX_EMBED_CHARS_PER_MESSAGE = 6000  # メッセージ内 embed 合計の Discord 制限
EMBED_TITLE_MAX = 256
EMBED_DESCRIPTION_MAX = 4096
MAX_SOURCE_LINKS = 5
MESSAGE_INTERVAL_SECONDS = 1.0  # 連投時の 429 予防
RETRY_AFTER_CAP_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 10


class SendFailure(Exception):
    """webhook 送信の失敗(429 の1回再送でも回復しなかった場合を含む)。"""


def importance_stars(importance: int) -> str:
    filled = min(max(importance, 1), 5)
    return "★" * filled + "☆" * (5 - filled)


def build_description(topic: dict[str, Any]) -> str:
    """summary + 空行 + 出典リンク行。4096字を超える場合はリンクを削って収める(summaryは削らない)。"""
    sources = topic["sources"][:MAX_SOURCE_LINKS]
    for count in range(len(sources), 0, -1):
        links = " / ".join(f"[{s['name']}]({s['url']})" for s in sources[:count])
        description = f"{topic['summary']}\n\n出典: {links}"
        if len(description) <= EMBED_DESCRIPTION_MAX:
            return description
    return topic["summary"][:EMBED_DESCRIPTION_MAX]


def build_embed(topic: dict[str, Any], color: int, timestamp: str) -> dict[str, Any]:
    title = f"{importance_stars(topic['importance'])} {topic['headline']}"[:EMBED_TITLE_MAX]
    return {
        "title": title,
        "description": build_description(topic),
        "url": topic["sources"][0]["url"],
        "color": color,
        "timestamp": timestamp,
    }


def embed_char_count(embed: dict[str, Any]) -> int:
    return len(embed["title"]) + len(embed["description"])


def pack_embeds(embeds: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """embed 10個/合計6000字の制限内に収まるようメッセージ単位に分割する。"""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for embed in embeds:
        size = embed_char_count(embed)
        if current and (
            len(current) >= MAX_EMBEDS_PER_MESSAGE
            or current_chars + size > MAX_EMBED_CHARS_PER_MESSAGE
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(embed)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _retry_after_seconds(response: requests.Response) -> float:
    value = response.headers.get("Retry-After")
    if value is None:
        try:
            value = response.json().get("retry_after")
        except ValueError:
            value = None
    try:
        seconds = float(value) if value is not None else 1.0
    except (TypeError, ValueError):
        seconds = 1.0
    return min(max(seconds, 0.0), RETRY_AFTER_CAP_SECONDS)


def send_message(webhook_url: str, payload: dict[str, Any]) -> None:
    """1メッセージを送信する。429 は Retry-After 秒待機して1回だけ再送する。"""
    response = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 429:
        wait = _retry_after_seconds(response)
        logging.warning("rate limited (429); retrying once after %.1fs", wait)
        time.sleep(wait)
        response = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    if not response.ok:
        raise SendFailure(f"HTTP {response.status_code}: {response.text[:200]}")


def load_category_meta() -> dict[str, dict[str, Any]]:
    with FEEDS_PATH.open(encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)
    return {
        c["id"]: {"name": c["name"], "color": c["color"], "webhook_env": c["webhook_env"]}
        for c in config["categories"]
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()

    try:
        with DIGEST_PATH.open(encoding="utf-8") as f:
            digest: dict[str, Any] = json.load(f)
    except (OSError, ValueError) as exc:
        logging.error("cannot read %s: %s", DIGEST_PATH, exc)
        return 1

    today = datetime.now(JST).strftime("%Y-%m-%d")
    if digest.get("date") != today:
        logging.error(
            "digest date %r is not today %r (JST); refusing to re-deliver stale digest",
            digest.get("date"),
            today,
        )
        return 1

    meta_by_id = load_category_meta()
    timestamp = datetime.now(JST).isoformat(timespec="seconds")
    failures = 0
    sent_messages = 0

    for category in digest["categories"]:
        category_id = category["id"]
        topics = category["topics"]
        if not topics:
            logging.info("category %s: no topics; skipping", category_id)
            continue
        meta = meta_by_id.get(category_id)
        if meta is None:
            logging.error("category %s: not defined in feeds.yaml", category_id)
            failures += 1
            continue
        webhook_url = os.getenv(meta["webhook_env"], "").strip()
        if not webhook_url:
            logging.error("category %s: env %s is not set", category_id, meta["webhook_env"])
            failures += 1
            continue

        embeds = [build_embed(topic, meta["color"], timestamp) for topic in topics]
        batches = pack_embeds(embeds)
        for index, batch in enumerate(batches, start=1):
            content = f"📰 {digest['date']} ダイジェスト — {meta['name']}"
            if len(batches) > 1:
                content += f" ({index}/{len(batches)})"
            if sent_messages:
                time.sleep(MESSAGE_INTERVAL_SECONDS)
            try:
                send_message(webhook_url, {"content": content, "embeds": batch})
            except (SendFailure, requests.RequestException) as exc:
                logging.error("category %s: send failed: %s", category_id, exc)
                failures += 1
                break
            sent_messages += 1
            logging.info(
                "category %s: sent message %d/%d (%d embeds)",
                category_id,
                index,
                len(batches),
                len(batch),
            )

    if failures:
        logging.error("%d categor%s failed", failures, "y" if failures == 1 else "ies")
        return 1
    logging.info("done: %d message(s) sent", sent_messages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
