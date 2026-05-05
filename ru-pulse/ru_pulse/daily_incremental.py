"""Daily incremental fetcher. Fetches only posts whose msg_id is greater
than the highest already in the corpus per channel.

Stops paginating as soon as it crosses the watermark — typical run is
~5 min for 50 channels (one or two pages each).
Designed to run from cron daily. Failures alert via the same logging
infra; it returns non-zero on errors so a wrapper can TG-alert.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import sanitize, storage
from .fetch import (BASE, PAGINATED, _http_get, _now_iso, _parse_post, _parse_channels,
                    _earliest_msg_id, _delay,
                    CIRCUIT_BREAKER, FetchStats)

LOG = logging.getLogger("ru_pulse.daily_incremental")


def _watermarks(db_path: Path) -> dict[str, int]:
    """Return {channel: max_msg_id_seen}."""
    out: dict[str, int] = {}
    with storage.connect(db_path) as c:
        rows = c.execute(
            "SELECT channel, MAX(msg_id) AS m FROM posts GROUP BY channel"
        ).fetchall()
        for r in rows:
            out[r["channel"]] = r["m"]
    return out


def fetch_incremental(channel: str, since: int, max_pages: int,
                      session: requests.Session) -> list[dict]:
    """Fetch all posts with msg_id > since. Stops at first page where
    everything is older or earliest_msg_id <= since."""
    new_posts: list[dict] = []
    seen: set[int] = set()
    next_url = BASE.format(channel=channel)
    page = 0
    while next_url and page < max_pages:
        page += 1
        LOG.info("channel=%s page=%d url=%s have=%d watermark=%d",
                 channel, page, next_url, len(new_posts), since)
        resp = _http_get(next_url, session)
        if not resp:
            break
        soup = BeautifulSoup(resp.text, "lxml")
        page_new = []
        all_ids_on_page: list[int] = []
        for div in soup.select(".tgme_widget_message[data-post]"):
            p = _parse_post(div, channel)
            if not p:
                continue
            all_ids_on_page.append(p["msg_id"])
            if p["msg_id"] <= since:
                continue
            if p["msg_id"] in seen:
                continue
            seen.add(p["msg_id"])
            page_new.append(p)
        new_posts.extend(page_new)

        # If everything on this page is at or below the watermark, we're done.
        if all_ids_on_page and min(all_ids_on_page) <= since:
            break
        earliest = _earliest_msg_id(soup)
        if earliest is None or earliest <= 1:
            break
        next_url = PAGINATED.format(channel=channel, before=earliest)
        _delay()
    return new_posts


def run(channels: list[tuple[str, str]], db_path: Path = storage.DB_PATH,
        max_pages: int = 5) -> tuple[FetchStats, dict]:
    storage.init_db(db_path)
    stats = FetchStats()
    consecutive_fails = 0
    session = requests.Session()
    started = _now_iso()
    with storage.connect(db_path) as conn:
        run_id = storage.start_run(conn, started)

    watermarks = _watermarks(db_path)
    per_channel = {}

    for name, bucket in channels:
        since = watermarks.get(name, 0)
        try:
            posts = fetch_incremental(name, since, max_pages, session)
        except Exception as e:
            LOG.exception("fatal channel=%s", name)
            stats.errors.append(f"{name}: {e!r}")
            consecutive_fails += 1
            if consecutive_fails >= CIRCUIT_BREAKER:
                stats.errors.append("CIRCUIT_BREAKER_TRIPPED")
                break
            continue
        per_channel[name] = len(posts)

        # 0 new posts is normal in incremental mode — channel is just
        # quiet today. Reset the consecutive-fails counter and move on.
        if not posts:
            consecutive_fails = 0
            continue
        consecutive_fails = 0

        with storage.connect(db_path) as conn:
            now = _now_iso()
            storage.upsert_channel(conn, name, bucket, None, now)
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
    return stats, per_channel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Incremental TG fetcher; cron-friendly")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--channels", help="comma-separated channel:bucket pairs")
    src.add_argument("--channels-file", help="path to file with channel:bucket per line")
    ap.add_argument("--max-pages", type=int, default=5,
                    help="max pages back to scan per channel (default 5; rare to need more)")
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

    stats, per_channel = run(channels, max_pages=args.max_pages)
    print(f"\n[incremental] new={stats.new} dup={stats.dup} q={stats.quarantined}")
    if any(per_channel.values()):
        print("[per-channel new posts]")
        for name, n in sorted(per_channel.items(), key=lambda kv: -kv[1]):
            if n > 0:
                print(f"  {name:<28} +{n}")
    if stats.errors:
        print(f"[errors] {'; '.join(stats.errors)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
