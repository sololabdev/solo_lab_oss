"""SQLite storage for RU Pulse corpus.

Schema is intentionally minimal and append-only. Every row is traceable
back to its source URL + fetch timestamp. Quarantine table holds posts
that failed sanitize layer 1 — they are NEVER fed into the analysis pipeline.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    name           TEXT PRIMARY KEY,
    bucket         TEXT NOT NULL,
    title          TEXT,
    first_seen_at  TEXT NOT NULL,
    last_fetched   TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    channel        TEXT NOT NULL,
    msg_id         INTEGER NOT NULL,
    posted_at      TEXT NOT NULL,
    text           TEXT NOT NULL,
    text_hash      TEXT NOT NULL,
    views          TEXT,
    forwarded_from TEXT,
    has_media      INTEGER NOT NULL DEFAULT 0,
    html_url       TEXT NOT NULL,
    fetched_at     TEXT NOT NULL,
    fetcher_ver    TEXT NOT NULL,
    PRIMARY KEY (channel, msg_id),
    FOREIGN KEY (channel) REFERENCES channels(name)
);

CREATE TABLE IF NOT EXISTS quarantine (
    channel         TEXT NOT NULL,
    msg_id          INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    matched_pattern TEXT,
    matched_text    TEXT,
    raw_text        TEXT NOT NULL,
    flagged_at      TEXT NOT NULL,
    PRIMARY KEY (channel, msg_id)
);

CREATE TABLE IF NOT EXISTS fetch_runs (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    channels_n     INTEGER,
    posts_new      INTEGER,
    posts_dup      INTEGER,
    posts_quarant  INTEGER,
    errors         TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_channel_date ON posts(channel, posted_at);
CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts(text_hash);
"""

DB_PATH = Path(__file__).parent / "data" / "corpus.db"
FETCHER_VERSION = "0.1.0"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def connect(path: Path | None = None):
    """Open a SQLite connection. Path resolves at CALL time so callers/tests
    can monkeypatch `storage.DB_PATH` and have the override take effect."""
    if path is None:
        path = DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    if path is None:
        path = DB_PATH
    with connect(path) as c:
        c.executescript(SCHEMA)


def upsert_channel(conn, name: str, bucket: str, title: str | None, now: str) -> None:
    conn.execute(
        """INSERT INTO channels(name, bucket, title, first_seen_at, last_fetched)
           VALUES(?,?,?,?,?)
           ON CONFLICT(name) DO UPDATE SET
               last_fetched = excluded.last_fetched,
               title = COALESCE(excluded.title, channels.title)""",
        (name, bucket, title, now, now),
    )


def insert_post(conn, post: dict) -> str:
    """Returns 'new' / 'dup'. Caller handles quarantine separately."""
    try:
        conn.execute(
            """INSERT INTO posts(channel, msg_id, posted_at, text, text_hash,
                                  views, forwarded_from, has_media,
                                  html_url, fetched_at, fetcher_ver)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                post["channel"], post["msg_id"], post["posted_at"],
                post["text"], post["text_hash"], post.get("views"),
                post.get("forwarded_from"), int(post.get("has_media", False)),
                post["html_url"], post["fetched_at"], FETCHER_VERSION,
            ),
        )
        return "new"
    except sqlite3.IntegrityError:
        return "dup"


def insert_quarantine(conn, channel: str, msg_id: int, reason: str,
                      pattern: str | None, matched_text: str | None,
                      raw_text: str, now: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO quarantine
               (channel, msg_id, reason, matched_pattern, matched_text,
                raw_text, flagged_at)
           VALUES(?,?,?,?,?,?,?)""",
        (channel, msg_id, reason, pattern, matched_text, raw_text, now),
    )


def start_run(conn, now: str) -> int:
    cur = conn.execute(
        "INSERT INTO fetch_runs(started_at) VALUES(?)", (now,)
    )
    return cur.lastrowid


def finish_run(conn, run_id: int, finished_at: str,
               channels_n: int, new: int, dup: int, q: int, errors: str) -> None:
    conn.execute(
        """UPDATE fetch_runs SET finished_at=?, channels_n=?,
               posts_new=?, posts_dup=?, posts_quarant=?, errors=?
           WHERE run_id=?""",
        (finished_at, channels_n, new, dup, q, errors, run_id),
    )


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
