"""Spot-check helper. Picks N random posts from corpus.db and prints
url + first ~300 chars of stored text so a human can verify against t.me UI.

Usage:
    python -m solo_lab_system.research.ru_pulse.verify --n 10
    python -m solo_lab_system.research.ru_pulse.verify --channel neuraldeep --n 5
"""
from __future__ import annotations

import argparse
import sys

from . import storage


def sample(n: int = 10, channel: str | None = None) -> None:
    with storage.connect() as c:
        if channel:
            cur = c.execute(
                "SELECT channel, msg_id, posted_at, text, views, html_url, "
                "       fetched_at, has_media, forwarded_from "
                "FROM posts WHERE channel=? "
                "ORDER BY RANDOM() LIMIT ?",
                (channel, n),
            )
        else:
            cur = c.execute(
                "SELECT channel, msg_id, posted_at, text, views, html_url, "
                "       fetched_at, has_media, forwarded_from "
                "FROM posts ORDER BY RANDOM() LIMIT ?",
                (n,),
            )
        rows = cur.fetchall()
    if not rows:
        print("[verify] no posts in corpus")
        return

    print(f"[verify] sampled {len(rows)} posts. Open the URL, compare text.\n")
    for i, r in enumerate(rows, 1):
        print(f"--- {i}/{len(rows)} ---")
        print(f"channel: {r['channel']}    msg_id: {r['msg_id']}")
        print(f"posted_at: {r['posted_at']}    views: {r['views']}    media: {bool(r['has_media'])}")
        if r["forwarded_from"]:
            print(f"forwarded_from: {r['forwarded_from']}")
        print(f"url: {r['html_url']}")
        print(f"fetched_at: {r['fetched_at']}")
        text = (r["text"] or "")[:300]
        if len(r["text"] or "") > 300:
            text += " […]"
        print(f"text: {text}")
        print()


def quarantine_dump(limit: int = 50) -> None:
    """Show what got filtered out — auditable failure mode review."""
    with storage.connect() as c:
        cur = c.execute(
            "SELECT channel, msg_id, reason, matched_pattern, raw_text, flagged_at "
            "FROM quarantine ORDER BY flagged_at DESC LIMIT ?", (limit,),
        )
        rows = cur.fetchall()
    if not rows:
        print("[quarantine] empty — no posts flagged")
        return
    print(f"[quarantine] {len(rows)} flagged post(s):\n")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['channel']}/{r['msg_id']}  pattern={r['reason']}  matched={r['matched_pattern']!r}")
        print(f"   raw: {(r['raw_text'] or '')[:160]}")
        print()


def stats() -> None:
    with storage.connect() as c:
        ch = c.execute(
            "SELECT channel, COUNT(*) AS n, MIN(posted_at) AS oldest, "
            "       MAX(posted_at) AS newest "
            "FROM posts GROUP BY channel ORDER BY channel"
        ).fetchall()
        total = c.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        q = c.execute("SELECT COUNT(*) AS n FROM quarantine").fetchone()["n"]
        runs = c.execute(
            "SELECT run_id, started_at, finished_at, channels_n, posts_new, "
            "       posts_dup, posts_quarant FROM fetch_runs "
            "ORDER BY run_id DESC LIMIT 5"
        ).fetchall()
    print(f"[stats] total_posts={total}  quarantined={q}\n")
    print("per-channel:")
    for r in ch:
        print(f"  {r['channel']:<24} n={r['n']:<5} {r['oldest']}  ->  {r['newest']}")
    print("\nrecent runs:")
    for r in runs:
        print(f"  run#{r['run_id']:<3} ch={r['channels_n']} "
              f"new={r['posts_new']} dup={r['posts_dup']} q={r['posts_quarant']} "
              f"started={r['started_at']}  finished={r['finished_at']}")


def integrity() -> int:
    """Sanity checks on the corpus DB. Returns 0 OK, 1 if any check fails.
    - posts.channel must FK-resolve into channels.name
    - text_hash should be unique per (channel, msg_id) but not globally
    - no posts without html_url, posted_at, fetched_at
    - quarantine + posts must be disjoint by (channel, msg_id)
    """
    failures: list[str] = []
    with storage.connect() as c:
        orphan_ch = c.execute(
            "SELECT COUNT(*) AS n FROM posts p "
            "LEFT JOIN channels ch ON p.channel = ch.name "
            "WHERE ch.name IS NULL"
        ).fetchone()["n"]
        if orphan_ch:
            failures.append(f"{orphan_ch} posts reference unknown channel")

        bad_meta = c.execute(
            "SELECT COUNT(*) AS n FROM posts "
            "WHERE html_url IS NULL OR html_url = '' "
            "   OR posted_at IS NULL OR posted_at = '' "
            "   OR fetched_at IS NULL OR fetched_at = ''"
        ).fetchone()["n"]
        if bad_meta:
            failures.append(f"{bad_meta} posts with missing required metadata")

        overlap = c.execute(
            "SELECT COUNT(*) AS n FROM quarantine q "
            "JOIN posts p ON q.channel = p.channel AND q.msg_id = p.msg_id"
        ).fetchone()["n"]
        if overlap:
            failures.append(f"{overlap} rows present in BOTH posts and quarantine")

        empty_text = c.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE text IS NULL"
        ).fetchone()["n"]
        if empty_text:
            failures.append(f"{empty_text} posts with NULL text (schema violation)")

        n_posts = c.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        n_channels = c.execute("SELECT COUNT(*) AS n FROM channels").fetchone()["n"]
        n_quarantine = c.execute("SELECT COUNT(*) AS n FROM quarantine").fetchone()["n"]

    print(f"[integrity] channels={n_channels} posts={n_posts} quarantine={n_quarantine}")
    if not failures:
        print("[integrity] OK")
        return 0
    print(f"[integrity] FAIL — {len(failures)} issue(s):")
    for f in failures:
        print(f"  - {f}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="sample size")
    ap.add_argument("--channel", help="filter to one channel")
    ap.add_argument("--mode",
                    choices=["sample", "quarantine", "stats", "integrity"],
                    default="sample")
    args = ap.parse_args(argv)

    if args.mode == "sample":
        sample(args.n, args.channel)
    elif args.mode == "quarantine":
        quarantine_dump(args.n)
    elif args.mode == "stats":
        stats()
    elif args.mode == "integrity":
        return integrity()
    return 0


if __name__ == "__main__":
    sys.exit(main())
