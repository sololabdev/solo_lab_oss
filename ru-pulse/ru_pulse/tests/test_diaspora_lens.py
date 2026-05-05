"""Tests for diaspora_lens.py — synthetic DB, no production data."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import diaspora_lens, storage


@pytest.fixture
def synthetic_db(tmp_path, monkeypatch):
    db = tmp_path / "test_corpus.db"
    storage.init_db(db)
    monkeypatch.setattr(storage, "DB_PATH", db)
    monkeypatch.setattr(diaspora_lens, "REPORTS", tmp_path / "reports")
    (tmp_path / "reports").mkdir()

    with storage.connect(db) as c:
        # diaspora_relocant — 2 channels with focused vocab
        storage.upsert_channel(c, "relocant1", "diaspora_relocant", None, "now")
        storage.upsert_channel(c, "relocant2", "diaspora_relocant", None, "now")
        # ai_core — different vocab
        storage.upsert_channel(c, "ai1", "ai_core", None, "now")
        storage.upsert_channel(c, "ai2", "ai_core", None, "now")

        diaspora_posts = [
            ("relocant1", 1, "Виза релокация банк налоги Израиль"),
            ("relocant1", 2, "Релокация банк счёт Берлин виза"),
            ("relocant1", 3, "Налоги в эмиграции счёт банк виза"),
            ("relocant1", 4, "Резидентство паспорт виза налоги"),
            ("relocant1", 5, "Банк счёт открыть релокация виза"),
            ("relocant2", 6, "Эмиграция налоги виза резидентство"),
            ("relocant2", 7, "Банк счёт релокация налоги Берлин"),
            ("relocant2", 8, "Виза резидентство налоги банк счёт"),
        ]
        ai_posts = [
            ("ai1", 100, "claude opus context window inference"),
            ("ai1", 101, "claude sonnet api streaming inference"),
            ("ai1", 102, "claude code cli инструмент"),
            ("ai2", 103, "openai gpt sonnet inference latency"),
            ("ai2", 104, "claude sonnet stream inference"),
        ]
        for ch, mid, txt in diaspora_posts + ai_posts:
            storage.insert_post(c, {
                "channel": ch, "msg_id": mid,
                "posted_at": "2026-05-01T00:00:00+00:00",
                "text": txt, "text_hash": storage.text_hash(txt),
                "views": "1K", "forwarded_from": None, "has_media": False,
                "html_url": f"https://t.me/{ch}/{mid}", "fetched_at": "now",
            })
    return db


def test_channels_in_bucket(synthetic_db):
    chs = diaspora_lens._channels_in_bucket("diaspora_relocant")
    assert set(chs) == {"relocant1", "relocant2"}


def test_unknown_bucket_raises(synthetic_db):
    with pytest.raises(ValueError):
        diaspora_lens.lens("nonexistent_bucket")


def test_lens_extracts_distinctive_terms(synthetic_db):
    report = diaspora_lens.lens("diaspora_relocant", top_k=20)
    assert report["bucket"] == "diaspora_relocant"
    assert report["n_channels"] == 2
    assert report["n_posts"] == 8

    top = [r["term"] for r in report["top_lift_terms"]]
    # diaspora-specific terms should rank high
    assert any(t in ("виза", "банк", "налоги", "релокация") for t in top), \
        f"expected diaspora terms in lift table, got top={top[:10]}"


def test_lens_cross_bucket_jaccard_sorted(synthetic_db):
    report = diaspora_lens.lens("diaspora_relocant")
    cross = report["cross_bucket_jaccard"]
    # Jaccard should be sorted descending
    jaccs = [r["jaccard"] for r in cross]
    assert jaccs == sorted(jaccs, reverse=True)
    # ai_core should appear (it's the only other bucket with data)
    assert any(r["other_bucket"] == "ai_core" for r in cross)


def test_render_md_produces_valid_sections(synthetic_db):
    report = diaspora_lens.lens("diaspora_relocant")
    md = diaspora_lens.render_md(report)
    assert "# Lens — `diaspora_relocant`" in md
    assert "Top distinctive terms" in md
    assert "Closest other buckets" in md
    assert "relocant1" in md or "relocant2" in md


def test_lens_handles_bucket_with_no_voice_data(synthetic_db):
    """voice_centroid empty when fingerprint JSON missing — must not crash."""
    report = diaspora_lens.lens("diaspora_relocant")
    assert "voice_centroid" in report
    assert report["voice_centroid"] == {}
    assert report["voice_delta_vs_corpus_mean"] == {}


def test_cross_bucket_jaccard_is_deterministic(synthetic_db):
    """Two calls with identical data must produce identical Jaccard values
    (set ordering must NOT leak hash randomness into output)."""
    r1 = diaspora_lens.lens("diaspora_relocant")
    r2 = diaspora_lens.lens("diaspora_relocant")
    j1 = [(r["other_bucket"], r["jaccard"]) for r in r1["cross_bucket_jaccard"]]
    j2 = [(r["other_bucket"], r["jaccard"]) for r in r2["cross_bucket_jaccard"]]
    assert j1 == j2


def test_main_rejects_invalid_bucket_arg():
    """CLI must reject bucket names that could traverse paths or inject."""
    with pytest.raises(SystemExit):
        diaspora_lens.main(["--bucket", "../etc/passwd"])
    with pytest.raises(SystemExit):
        diaspora_lens.main(["--bucket", "Bad Bucket"])
    with pytest.raises(SystemExit):
        diaspora_lens.main(["--bucket", "x"])  # too short
