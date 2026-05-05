"""Tests for storage layer using `:memory:` SQLite — no FS access."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import storage


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test_corpus.db"
    storage.init_db(p)
    return p


def test_init_db_creates_all_tables(db_path):
    with storage.connect(db_path) as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {r["name"] for r in rows}
    assert {"channels", "posts", "quarantine", "fetch_runs"} <= names


def test_text_hash_is_stable():
    a = storage.text_hash("hello")
    b = storage.text_hash("hello")
    assert a == b
    assert len(a) == 64
    assert a != storage.text_hash("hello!")


def test_upsert_channel_inserts_then_updates(db_path):
    with storage.connect(db_path) as c:
        storage.upsert_channel(c, "addmeto", "dev", "Бобук", "2026-05-02T00:00:00+00:00")
        storage.upsert_channel(c, "addmeto", "dev", None, "2026-05-02T01:00:00+00:00")
    with storage.connect(db_path) as c:
        rows = c.execute("SELECT * FROM channels WHERE name='addmeto'").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "Бобук"  # not overwritten with None
    assert rows[0]["last_fetched"] == "2026-05-02T01:00:00+00:00"


def test_insert_post_dedup(db_path):
    with storage.connect(db_path) as c:
        storage.upsert_channel(c, "addmeto", "dev", None, "now")
        post = {
            "channel": "addmeto", "msg_id": 42,
            "posted_at": "2026-05-02T00:00:00+00:00",
            "text": "hi", "text_hash": storage.text_hash("hi"),
            "views": "1K", "forwarded_from": None, "has_media": False,
            "html_url": "https://t.me/addmeto/42", "fetched_at": "now",
        }
        assert storage.insert_post(c, post) == "new"
        assert storage.insert_post(c, post) == "dup"


def test_insert_quarantine_replace(db_path):
    with storage.connect(db_path) as c:
        storage.insert_quarantine(
            c, "addmeto", 42,
            reason="prompt_injection", pattern="ignore_prev",
            matched_text="ignore previous", raw_text="hi",
            now="2026-05-02T00:00:00+00:00",
        )
        # Same key — REPLACE behavior
        storage.insert_quarantine(
            c, "addmeto", 42,
            reason="prompt_injection", pattern="role_override",
            matched_text="you are now", raw_text="hi v2",
            now="2026-05-02T01:00:00+00:00",
        )
    with storage.connect(db_path) as c:
        rows = c.execute("SELECT * FROM quarantine").fetchall()
    assert len(rows) == 1
    assert rows[0]["matched_pattern"] == "role_override"
    assert rows[0]["matched_text"] == "you are now"


def test_run_lifecycle(db_path):
    with storage.connect(db_path) as c:
        run_id = storage.start_run(c, "2026-05-02T00:00:00+00:00")
    assert isinstance(run_id, int)
    with storage.connect(db_path) as c:
        storage.finish_run(
            c, run_id, "2026-05-02T01:00:00+00:00",
            channels_n=5, new=100, dup=0, q=2, errors=""
        )
    with storage.connect(db_path) as c:
        row = c.execute("SELECT * FROM fetch_runs WHERE run_id=?", (run_id,)).fetchone()
    assert row["posts_new"] == 100
    assert row["posts_quarant"] == 2
    assert row["finished_at"] == "2026-05-02T01:00:00+00:00"


def test_connect_rolls_back_on_exception(db_path):
    """C1 — verify rollback fires on exception inside the context manager."""
    with pytest.raises(RuntimeError):
        with storage.connect(db_path) as c:
            storage.upsert_channel(c, "rollback_test", "dev", "x", "now")
            raise RuntimeError("simulated failure")

    # The half-written upsert must NOT be visible after rollback.
    with storage.connect(db_path) as c:
        rows = c.execute(
            "SELECT * FROM channels WHERE name='rollback_test'"
        ).fetchall()
    assert rows == []


def test_wal_mode_is_enabled(db_path):
    with storage.connect(db_path) as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
