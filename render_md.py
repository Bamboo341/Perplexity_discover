"""render_md.py — sink B: data/digest.json を md に描画し、README とアーカイブを更新する。

- digest.json の date が当日(JST)でなければ描画せず exit 1(前日分の再配信防止。Digest_spec.md §7)
- 出力1: digest/YYYY-MM-DD.md(ファイル名の日付は digest.json の date)
- 出力2: README.md(全文を機械生成。最新リンク + 直近7日分)
- 出力3: data/digest.json を data/archive/YYYY-MM-DD.json へコピー(移動ではない)
- git 操作は行わない(bat 側の責務)
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

JST = timezone(timedelta(hours=9))
DIGEST_PATH = Path("data/digest.json")
FEEDS_PATH = Path("feeds.yaml")
DIGEST_DIR = Path("digest")
ARCHIVE_DIR = Path("data/archive")
README_PATH = Path("README.md")
MAX_SOURCE_LINKS = 5
README_RECENT_COUNT = 7
DATE_MD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def importance_stars(importance: int) -> str:
    filled = min(max(importance, 1), 5)
    return "★" * filled + "☆" * (5 - filled)


def render_topic(topic: dict[str, Any]) -> str:
    links = " / ".join(
        f"[{source['name']}]({source['url']})" for source in topic["sources"][:MAX_SOURCE_LINKS]
    )
    return (
        f"### {importance_stars(topic['importance'])} {topic['headline']}\n"
        f"{topic['summary']}\n\n"
        f"出典: {links}\n"
    )


def render_digest_md(digest: dict[str, Any], name_by_id: dict[str, str]) -> str:
    parts = [f"# 📰 {digest['date']} ダイジェスト\n"]
    for category in digest["categories"]:
        if not category["topics"]:
            continue
        parts.append(f"## {name_by_id.get(category['id'], category['id'])}\n")
        parts.extend(render_topic(topic) for topic in category["topics"])
    return "\n".join(parts)


def list_digest_dates() -> list[str]:
    if not DIGEST_DIR.is_dir():
        return []
    return sorted(
        (path.stem for path in DIGEST_DIR.iterdir() if DATE_MD_RE.match(path.name)),
        reverse=True,
    )


def render_readme(dates: list[str]) -> str:
    lines = [
        "# 📰 discover-digest",
        "",
        "RSS × Claude Code による毎朝のニュースダイジェスト。このファイルは render_md.py が自動生成する。",
        "",
    ]
    if dates:
        lines.append(f"最新: [{dates[0]}](digest/{dates[0]}.md)")
    else:
        lines.append("最新: (まだダイジェストはありません)")
    lines += ["", "## 直近7日", ""]
    lines += [f"- [{date}](digest/{date}.md)" for date in dates[:README_RECENT_COUNT]]
    return "\n".join(lines) + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        with DIGEST_PATH.open(encoding="utf-8") as f:
            digest: dict[str, Any] = json.load(f)
    except (OSError, ValueError) as exc:
        logging.error("cannot read %s: %s", DIGEST_PATH, exc)
        return 1

    today = datetime.now(JST).strftime("%Y-%m-%d")
    if digest.get("date") != today:
        logging.error(
            "digest date %r is not today %r (JST); refusing to re-render stale digest",
            digest.get("date"),
            today,
        )
        return 1

    with FEEDS_PATH.open(encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)
    name_by_id = {c["id"]: c["name"] for c in config["categories"]}
    date = digest["date"]

    try:
        DIGEST_DIR.mkdir(parents=True, exist_ok=True)
        md_path = DIGEST_DIR / f"{date}.md"
        md_path.write_text(render_digest_md(digest, name_by_id), encoding="utf-8")
        logging.info("wrote %s", md_path)

        README_PATH.write_text(render_readme(list_digest_dates()), encoding="utf-8")
        logging.info("wrote %s", README_PATH)

        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = ARCHIVE_DIR / f"{date}.json"
        shutil.copyfile(DIGEST_PATH, archive_path)  # コピー。transient 側は次回実行で上書きされる
        logging.info("copied %s -> %s", DIGEST_PATH, archive_path)
    except OSError as exc:
        logging.error("render failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
