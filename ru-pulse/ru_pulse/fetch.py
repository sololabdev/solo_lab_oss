"""TG public-channel fetcher using server-rendered preview at t.me/s/<channel>.

NOT an MTProto client. NOT a logged-in scraper. Reads only what Telegram
serves to anonymous browsers. Respects robots-style etiquette:

- 3s delay + 1s jitter between requests
- Honest User-Agent with contact URL
- Exponential backoff on 429/503 (30s -> 2min -> stop)
- 15s request timeout
- Circuit breaker: 3 consecutive channel failures -> abort run

Returns parsed posts in dicts; storage is the caller's job.
"""
from __future__ import annotations

import argparse
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import sanitize, storage

LOG = logging.getLogger("ru_pulse.fetch")

UA = "Solo-Lab-Research/0.1 (+https://solo-lab.dev/research)"
BASE = "https://t.me/s/{channel}"
PAGINATED = "https://t.me/s/{channel}?before={before}"

REQ_DELAY = 3.0
REQ_JITTER = 1.0
REQ_TIMEOUT = 15
MAX_RETRIES = 3
BACKOFF_BASE = 30.0
BACKOFF_CAP = 120.0
CIRCUIT_BREAKER = 3


@dataclass
class FetchStats:
    new: int = 0
    dup: int = 0
    quarantined: int = 0
    errors: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _delay() -> None:
    time.sleep(REQ_DELAY + random.uniform(0, REQ_JITTER))


def _http_get(url: str, session: requests.Session) -> requests.Response | None:
    """GET with backoff. Returns None if all retries exhausted."""
    backoff = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQ_TIMEOUT, headers={"User-Agent": UA})
        except requests.RequestException as e:
            LOG.warning("attempt=%d url=%s exc=%s", attempt, url, e)
            time.sleep(min(backoff, BACKOFF_CAP))
            backoff *= 2
            continue
        if r.status_code in (200,):
            return r
        if r.status_code == 404:
            LOG.warning("404 url=%s (channel may be private/deleted)", url)
            return None
        if r.status_code in (429, 503):
            LOG.warning("rate-limit %d url=%s sleep=%.1f", r.status_code, url, backoff)
            time.sleep(min(backoff, BACKOFF_CAP))
            backoff *= 2
            continue
        LOG.warning("status=%d url=%s body=%s", r.status_code, url, r.text[:120])
        return None
    return None


def _parse_post(div, channel: str) -> dict | None:
    """Extract one post dict from a tgme_widget_message div. Returns None if unparseable."""
    data_post = div.get("data-post")
    if not data_post or "/" not in data_post:
        return None
    msg_id_str = data_post.rsplit("/", 1)[1]
    if not msg_id_str.isdigit():
        return None
    msg_id = int(msg_id_str)

    text_el = div.select_one(".tgme_widget_message_text")
    text = text_el.get_text("\n", strip=True) if text_el else ""

    time_el = div.select_one(".tgme_widget_message_date time")
    posted_at = time_el.get("datetime") if time_el else None
    if not posted_at:
        return None

    views_el = div.select_one(".tgme_widget_message_views")
    views = views_el.get_text(strip=True) if views_el else None

    fwd_el = div.select_one(".tgme_widget_message_forwarded_from_name")
    forwarded_from = fwd_el.get_text(strip=True) if fwd_el else None

    has_media = bool(
        div.select_one(".tgme_widget_message_photo_wrap, .tgme_widget_message_video, "
                       ".tgme_widget_message_roundvideo, .tgme_widget_message_document, "
                       ".tgme_widget_message_voice")
    )

    if not text and not has_media:
        return None

    return {
        "channel": channel,
        "msg_id": msg_id,
        "posted_at": posted_at,
        "text": text,
        "text_hash": storage.text_hash(text),
        "views": views,
        "forwarded_from": forwarded_from,
        "has_media": has_media,
        "html_url": f"https://t.me/{channel}/{msg_id}",
        "fetched_at": _now_iso(),
    }


def _channel_title(soup: BeautifulSoup) -> str | None:
    el = soup.select_one(".tgme_channel_info_header_title span") \
         or soup.select_one(".tgme_channel_info_header_title")
    return el.get_text(strip=True) if el else None


def _earliest_msg_id(soup: BeautifulSoup) -> int | None:
    """Find smallest msg_id on page for pagination ?before=."""
    ids = []
    for div in soup.select(".tgme_widget_message[data-post]"):
        raw = div.get("data-post") or ""
        # bs4 attrs may be list-typed for multi-value attrs; data-post is single
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        v = raw.rsplit("/", 1)[-1]
        if v.isdigit():
            ids.append(int(v))
    return min(ids) if ids else None


def fetch_channel(channel: str, max_posts: int,
                  session: requests.Session) -> tuple[list[dict], str | None]:
    """Fetch up to max_posts most-recent posts from channel.

    Returns (posts, channel_title). Posts are NOT yet sanitized or stored.
    """
    posts: list[dict] = []
    seen_ids: set[int] = set()
    title: str | None = None
    next_url = BASE.format(channel=channel)
    page = 0

    while next_url and len(posts) < max_posts and page < 30:
        page += 1
        LOG.info("channel=%s page=%d url=%s have=%d", channel, page, next_url, len(posts))
        resp = _http_get(next_url, session)
        if not resp:
            break
        soup = BeautifulSoup(resp.text, "lxml")
        if title is None:
            title = _channel_title(soup)

        page_posts = []
        for div in soup.select(".tgme_widget_message[data-post]"):
            p = _parse_post(div, channel)
            if not p or p["msg_id"] in seen_ids:
                continue
            seen_ids.add(p["msg_id"])
            page_posts.append(p)

        if not page_posts:
            LOG.info("channel=%s page=%d no posts parsed, stopping", channel, page)
            break

        posts.extend(page_posts)
        earliest = _earliest_msg_id(soup)
        if earliest is None or earliest <= 1:
            break
        next_url = PAGINATED.format(channel=channel, before=earliest)
        _delay()

    posts.sort(key=lambda p: p["msg_id"], reverse=True)
    return posts[:max_posts], title


def run(channels: list[tuple[str, str]], max_posts: int,
        db_path: Path = storage.DB_PATH) -> FetchStats:
    """channels: list of (name, bucket). bucket = taxonomy label."""
    storage.init_db(db_path)
    stats = FetchStats()
    consecutive_fails = 0
    session = requests.Session()
    started = _now_iso()
    with storage.connect(db_path) as conn:
        run_id = storage.start_run(conn, started)

    for name, bucket in channels:
        try:
            posts, title = fetch_channel(name, max_posts, session)
        except Exception as e:
            LOG.exception("fatal channel=%s", name)
            stats.errors.append(f"{name}: {e!r}")
            consecutive_fails += 1
            if consecutive_fails >= CIRCUIT_BREAKER:
                LOG.error("circuit breaker tripped after %d consecutive fails", consecutive_fails)
                stats.errors.append("CIRCUIT_BREAKER_TRIPPED")
                break
            continue
        if not posts:
            # 0 posts != fetch failure; channel might be quiet or recently
            # cleaned. Log it but don't trip the circuit breaker — only HTTP
            # errors / exceptions should count toward CB.
            stats.errors.append(f"{name}: 0 posts (private/banned/empty?)")
            continue
        consecutive_fails = 0

        with storage.connect(db_path) as conn:
            now = _now_iso()
            storage.upsert_channel(conn, name, bucket, title, now)
            for p in posts:
                scan = sanitize.scan(p["text"])
                if not scan.safe:
                    storage.insert_quarantine(
                        conn, name, p["msg_id"],
                        "prompt_injection",
                        scan.matched_pattern,
                        scan.matched_text,
                        p["text"], now,
                    )
                    stats.quarantined += 1
                    continue
                outcome = storage.insert_post(conn, p)
                if outcome == "new":
                    stats.new += 1
                else:
                    stats.dup += 1

    finished = _now_iso()
    with storage.connect(db_path) as conn:
        storage.finish_run(
            conn, run_id, finished,
            channels_n=len(channels), new=stats.new, dup=stats.dup,
            q=stats.quarantined, errors="; ".join(stats.errors)[:2000],
        )
    return stats


_CHANNEL_NAME_RX = re.compile(r"^[A-Za-z0-9_]{3,64}$")
_BUCKET_NAME_RX = re.compile(r"^[a-z][a-z0-9_]{2,32}$")


def _parse_channels(text: str) -> list[tuple[str, str]]:
    """Strip line-comments first, THEN split on newlines/commas.
    Validates each (name, bucket) against strict allowlists — channel name
    flows directly into URL paths, so URL-injection is the threat model."""
    cleaned: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            cleaned.append(line)
    out: list[tuple[str, str]] = []
    for chunk in ",".join(cleaned).split(","):
        line = chunk.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"bad spec {line!r}, expected name:bucket")
        name, bucket = line.split(":", 1)
        name = name.strip()
        bucket = bucket.strip()
        if not _CHANNEL_NAME_RX.fullmatch(name):
            raise ValueError(
                f"invalid channel name {name!r}: must match [A-Za-z0-9_]{{3,64}}"
            )
        if not _BUCKET_NAME_RX.fullmatch(bucket):
            raise ValueError(
                f"invalid bucket {bucket!r}: must match [a-z][a-z0-9_]{{2,32}}"
            )
        out.append((name, bucket))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch RU TG channels into corpus.db")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--channels", help="comma-separated channel:bucket pairs")
    src.add_argument("--channels-file", help="path to file with channel:bucket per line ('#' comments)")
    ap.add_argument("--max-posts", type=int, default=20,
                    help="max posts per channel (default 20)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.channels_file:
        text = Path(args.channels_file).read_text()
    else:
        text = args.channels
    try:
        channels = _parse_channels(text)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    stats = run(channels, args.max_posts)
    print(f"\n[summary] new={stats.new} dup={stats.dup} quarantined={stats.quarantined}")
    if stats.errors:
        print(f"[errors] {'; '.join(stats.errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
