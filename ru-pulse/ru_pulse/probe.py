"""Quick probe of candidate channels — does t.me/s/<name> return 200
with at least one post? Used to validate the channel list before the
long fetch run. Sequential, polite (2s delay), prints alive/dead per name.
"""
from __future__ import annotations

import argparse
import sys
import time

import requests
from bs4 import BeautifulSoup

from .fetch import UA  # single source of truth for User-Agent string

DELAY = 2.0


def probe(name: str, session: requests.Session) -> tuple[str, int, int, str | None]:
    """Returns (name, http_status, posts_seen, title_or_none)."""
    url = f"https://t.me/s/{name}"
    try:
        r = session.get(url, headers={"User-Agent": UA}, timeout=15)
    except requests.RequestException as e:
        return (name, -1, 0, f"exc:{type(e).__name__}")
    if r.status_code != 200:
        return (name, r.status_code, 0, None)
    soup = BeautifulSoup(r.text, "lxml")
    posts = len(soup.select(".tgme_widget_message[data-post]"))
    title_el = (soup.select_one(".tgme_channel_info_header_title span")
                or soup.select_one(".tgme_channel_info_header_title"))
    title = title_el.get_text(strip=True) if title_el else None
    return (name, 200, posts, title)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", help="comma-separated channel handles")
    ap.add_argument("--delay", type=float, default=DELAY)
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.candidates.split(",") if n.strip()]
    s = requests.Session()
    alive: list[tuple[str, int, str | None]] = []
    dead: list[tuple[str, int, str | None]] = []
    print(f"Probing {len(names)} candidates @ {args.delay}s delay...\n")
    for i, name in enumerate(names, 1):
        n, code, posts, info = probe(name, s)
        ok = code == 200 and posts > 0
        marker = "OK " if ok else "X  "
        print(f"  {marker} [{i:>2}/{len(names)}] @{n:<28} status={code:<4} posts={posts:<3} title={info!r}")
        (alive if ok else dead).append((n, posts, info))
        if i < len(names):
            time.sleep(args.delay)
    print(f"\n[summary] alive={len(alive)} dead={len(dead)}")
    print("\nALIVE channels (use these):")
    for n, _p, _t in alive:
        print(f"  {n}")
    if dead:
        print("\nDEAD/empty (skip):")
        for n, _p, _t in dead:
            print(f"  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
