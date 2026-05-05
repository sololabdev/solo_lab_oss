"""Tests for topics analyzer — pure helpers, no DB."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import topics


def test_is_content_filters_stopwords():
    assert not topics.is_content("и")
    assert not topics.is_content("the")
    assert not topics.is_content("ab")  # too short
    assert not topics.is_content("123")
    assert topics.is_content("claude")
    assert topics.is_content("деплой")


def test_tokens_of_extracts_content_only():
    text = "Сегодня я тестировал claude code на проде"
    toks = topics.tokens_of(text)
    assert "claude" in toks
    assert "тестировал" in toks
    assert "code" in toks
    assert "проде" in toks
    # Stopwords filtered
    assert "и" not in toks
    assert "я" not in toks


def test_parse_iso_handles_storage_format():
    dt = topics.parse_iso("2026-05-02T07:34:57+00:00")
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.tzinfo is not None


def test_iso_year_week_format():
    dt = datetime(2026, 5, 2, tzinfo=timezone.utc)
    week = topics.iso_year_week(dt)
    # 2026-05-02 falls in ISO week 18
    assert week.startswith("2026-W")
    parts = week.split("-W")
    assert len(parts) == 2
    assert parts[1].isdigit()


def test_cadence_with_synthetic_rows():
    rows = [
        {"channel": "ch1", "posted_at": "2026-04-25T08:00:00+00:00", "text": "x"},
        {"channel": "ch1", "posted_at": "2026-04-26T08:00:00+00:00", "text": "y"},
        {"channel": "ch1", "posted_at": "2026-04-27T08:00:00+00:00", "text": "z"},
        {"channel": "ch2", "posted_at": "2025-01-01T00:00:00+00:00", "text": "old"},
    ]
    result = topics.cadence(rows)
    assert "ch1" in result
    assert "ch2" in result
    assert result["ch1"]["n_posts"] == 3
    assert result["ch1"]["span_days"] >= 1


def test_cadence_skips_invalid_dates():
    rows = [
        {"channel": "ok", "posted_at": "2026-04-25T08:00:00+00:00", "text": "x"},
        {"channel": "bad", "posted_at": "not-a-date", "text": "y"},
    ]
    result = topics.cadence(rows)
    assert "ok" in result
    assert "bad" not in result


def test_burst_detection_returns_per_channel():
    """Burst detection requires recent vs baseline; both buckets need posts."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(20):
        # Recent posts (last 28 days) about claude
        rows.append({
            "channel": "ch1",
            "posted_at": (now - timedelta(days=i + 1)).isoformat(),
            "text": "claude code на проде работает быстро",
        })
    for i in range(50):
        # Baseline (29-140 days ago) about gpt
        rows.append({
            "channel": "ch1",
            "posted_at": (now - timedelta(days=29 + i)).isoformat(),
            "text": "gpt openai api устаревший",
        })
    bursts = topics.burst_detection(rows)
    assert "ch1" in bursts
    assert "rising" in bursts["ch1"]
    assert "falling" in bursts["ch1"]


def test_cross_channel_topic_overlap_filters_low_count():
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=7)).isoformat()
    rows = [
        {"channel": "a", "posted_at": recent, "text": "claude code"},
        {"channel": "b", "posted_at": recent, "text": "claude api"},
        # Only 2 channels mention it — below the >=3 threshold
    ]
    out = topics.cross_channel_topic_overlap(rows)
    # term should not appear since only 2 channels have it
    terms = [r["term"] for r in out]
    assert "claude" not in terms
