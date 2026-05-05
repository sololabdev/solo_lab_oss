"""Tests for daily_incremental — watermark logic + parse-channels delegation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import daily_incremental, storage


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test_corpus.db"
    storage.init_db(p)
    return p


def _seed(db_path, channel: str, max_msg_id: int, bucket: str = "ai_core") -> None:
    with storage.connect(db_path) as c:
        storage.upsert_channel(c, channel, bucket, None, "now")
        for mid in range(1, max_msg_id + 1):
            text = f"post {mid}"
            storage.insert_post(c, {
                "channel": channel, "msg_id": mid,
                "posted_at": "2026-01-01T00:00:00+00:00",
                "text": text, "text_hash": storage.text_hash(text),
                "views": "1", "forwarded_from": None, "has_media": False,
                "html_url": f"https://t.me/{channel}/{mid}",
                "fetched_at": "now",
            })


def test_watermarks_returns_max_per_channel(db_path):
    _seed(db_path, "addmeto", 10)
    _seed(db_path, "neuraldeep", 50, bucket="dev")
    wm = daily_incremental._watermarks(db_path)
    assert wm == {"addmeto": 10, "neuraldeep": 50}


def test_watermarks_empty_db(db_path):
    wm = daily_incremental._watermarks(db_path)
    assert wm == {}


def test_parse_channels_uses_fetch_helper():
    """daily_incremental imports `_parse_channels` from fetch — verify it's
    the same function (not a divergent copy)."""
    from ru_pulse import fetch
    assert daily_incremental._parse_channels is fetch._parse_channels


def test_parse_channels_validates_names_in_incremental():
    """Channel name validation must apply when called from cron path."""
    with pytest.raises(ValueError):
        daily_incremental._parse_channels("evil/path:ai_core")


def test_fetch_incremental_stops_when_all_below_watermark(monkeypatch):
    """If every msg on the page is <= watermark, fetch_incremental stops
    after the first page (no infinite loop)."""

    class FakeResponse:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

    def fake_http_get(url, session):
        return FakeResponse('<div class="tgme_widget_message" data-post="x/5">'
                            '<div class="tgme_widget_message_text">old</div>'
                            '<a class="tgme_widget_message_date" href="x">'
                            '<time datetime="2025-01-01T00:00:00+00:00">x</time></a>'
                            '</div>')

    monkeypatch.setattr(daily_incremental, "_http_get", fake_http_get)
    monkeypatch.setattr(daily_incremental, "_delay", lambda: None)

    posts = daily_incremental.fetch_incremental(
        "x", since=10, max_pages=5, session=None
    )
    assert posts == []  # everything was below watermark


def test_fetch_incremental_collects_above_watermark(monkeypatch):
    """Above-watermark posts are kept; below-watermark are filtered."""

    class FakeResponse:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

    page = '''
    <div class="tgme_widget_message" data-post="x/15">
      <div class="tgme_widget_message_text">new fifteen</div>
      <a class="tgme_widget_message_date" href="x"><time datetime="2026-04-01T00:00:00+00:00">x</time></a>
    </div>
    <div class="tgme_widget_message" data-post="x/12">
      <div class="tgme_widget_message_text">old twelve</div>
      <a class="tgme_widget_message_date" href="x"><time datetime="2026-03-01T00:00:00+00:00">x</time></a>
    </div>
    '''
    monkeypatch.setattr(daily_incremental, "_http_get", lambda *a, **kw: FakeResponse(page))
    monkeypatch.setattr(daily_incremental, "_delay", lambda: None)

    posts = daily_incremental.fetch_incremental(
        "x", since=13, max_pages=2, session=None
    )
    msg_ids = [p["msg_id"] for p in posts]
    assert 15 in msg_ids
    assert 12 not in msg_ids
