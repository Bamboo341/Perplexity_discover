"""collect.py — パイプライン①: feeds.yaml の RSS を巡回・正規化し data/items.json を生成する。

取得は requests(タイムアウト10秒を確実に効かせるため)、パースは feedparser が担う。
失敗したフィードは WARN ログのみ出して続行し、全カテゴリ0件のときのみ exit 1 で
後続ステップを中止させる(Digest_spec.md §4)。
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
import yaml

JST = timezone(timedelta(hours=9))
FEEDS_PATH = Path("feeds.yaml")
OUTPUT_PATH = Path("data/items.json")
FETCH_TIMEOUT_SECONDS = 10
ADOPTION_WINDOW = timedelta(hours=24)
MAX_ITEMS_PER_CATEGORY = 60
SUMMARY_MAX_CHARS = 400
ID_HEX_LENGTH = 12
USER_AGENT = "discover-digest/1.0 (RSS collector)"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
# 記事を識別し得るクエリは残し、トラッキング系のみ除去する(Digest_spec.md §4)
TRACKING_PARAMS = {"fbclid", "gclid", "yclid", "msclkid", "mc_cid", "mc_eid", "igshid"}
TRACKING_PREFIXES = ("utm_",)


def normalize_text(raw: str) -> str:
    """HTMLタグ除去・エンティティのアンエスケープ・空白の正規化を行う。"""
    text = html.unescape(TAG_RE.sub(" ", raw))
    return WS_RE.sub(" ", text).strip()


def canonical_url(url: str) -> str:
    """重複判定用にトラッキング系クエリとフラグメントを除いたURLを返す。"""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not (key.lower().startswith(TRACKING_PREFIXES) or key.lower() in TRACKING_PARAMS)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def entry_item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:ID_HEX_LENGTH]


def published_jst(entry: Any) -> datetime | None:
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed_time:
        return None
    return datetime(*parsed_time[:6], tzinfo=timezone.utc).astimezone(JST)


def fetch_entries(feed_name: str, url: str) -> list[Any]:
    try:
        response = requests.get(
            url, timeout=FETCH_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning("feed fetch failed: %s (%s): %s", feed_name, url, exc)
        return []
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        logging.warning("feed parse failed: %s (%s): %s", feed_name, url, parsed.bozo_exception)
        return []
    if not parsed.entries:
        logging.warning("feed has no entries: %s (%s)", feed_name, url)
    return list(parsed.entries)


def collect_category(category: dict[str, Any], cutoff: datetime) -> list[dict[str, Any]]:
    dated: list[tuple[datetime, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()

    for feed in category["feeds"]:
        entries = fetch_entries(feed["name"], feed["url"])
        adopted = 0
        for entry in entries:
            url = (entry.get("link") or "").strip()
            title = normalize_text(entry.get("title") or "")
            if not url or not title:
                continue
            published = published_jst(entry)
            if published is not None and published < cutoff:
                continue
            item_id = entry_item_id(url)
            if item_id in seen_ids or title in seen_titles:
                continue
            seen_ids.add(item_id)
            seen_titles.add(title)
            item = {
                "id": item_id,
                "title": title,
                "url": url,
                "source": feed["name"],
                "published": published.isoformat(timespec="seconds") if published else None,
                "summary": normalize_text(entry.get("summary") or "")[:SUMMARY_MAX_CHARS],
            }
            if published:
                dated.append((published, item))
            else:
                undated.append(item)
            adopted += 1
        logging.info(
            "%s / %s: %d entries, %d adopted", category["id"], feed["name"], len(entries), adopted
        )

    dated.sort(key=lambda pair: pair[0], reverse=True)
    items = [item for _, item in dated] + undated  # 日時欠損は末尾
    return items[:MAX_ITEMS_PER_CATEGORY]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with FEEDS_PATH.open(encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)

    now = datetime.now(JST)
    cutoff = now - ADOPTION_WINDOW
    categories: list[dict[str, Any]] = []
    total_items = 0
    for category in config["categories"]:
        items = collect_category(category, cutoff)
        categories.append({"id": category["id"], "items": items})
        total_items += len(items)
        logging.info("category %s: %d items", category["id"], len(items))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": now.isoformat(timespec="seconds"), "categories": categories}
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if total_items == 0:
        logging.error("all categories are empty; aborting pipeline")
        return 1
    logging.info("wrote %s (%d items)", OUTPUT_PATH, total_items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
