"""Unit tests for weekly_pulse.py — deterministic logic only.
Snapshot + render + judge are tested with synthetic dicts; no DB required.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import weekly_pulse as wp


def _make_lexicon(channels: dict[str, dict]) -> dict:
    """channels = {channel_name: {"top_cyr": [(term, count), ...], "top_lat": [...]}} """
    per_channel = []
    for name, lists in channels.items():
        per_channel.append({
            "name": name,
            "n_posts": 100,
            "top_cyr": lists.get("top_cyr", []),
            "top_lat": lists.get("top_lat", []),
            "top_bigrams": [],
        })
    return {"per_channel": per_channel}


def _make_topics(cadence: dict) -> dict:
    return {"cadence": cadence}


def _make_voice(channels: list[dict]) -> dict:
    return {"raw": channels}


def test_diff_no_prev_returns_empty_lists():
    now = {
        "lexicon": _make_lexicon({"a": {"top_cyr": [("термин", 10)]}}),
        "topics": _make_topics({}),
        "voice": _make_voice([]),
    }
    d = wp.diff(now, None, anti_models=set())
    assert d.rising == []
    assert d.falling == []
    assert d.cadence_shifts == []
    assert d.hype is None
    assert d.data_ok is False


def test_diff_detects_rising_term():
    now = {
        "lexicon": _make_lexicon({
            "ch1": {"top_cyr": [("claude", 100)]},
            "ch2": {"top_cyr": [("claude", 50)]},
        }),
        "topics": _make_topics({}),
        "voice": _make_voice([]),
    }
    prev = {
        "lexicon": _make_lexicon({
            "ch1": {"top_cyr": [("claude", 30)]},
            "ch2": {"top_cyr": [("claude", 20)]},
        }),
        "topics": _make_topics({}),
        "voice": _make_voice([]),
    }
    d = wp.diff(now, prev, anti_models=set())
    assert d.data_ok is True
    assert len(d.rising) >= 1
    top = d.rising[0]
    assert top.term == "claude"
    assert top.count_now == 150
    assert top.count_prev == 50
    assert top.delta_pct == 200.0


def test_diff_detects_cadence_shift():
    now = {
        "lexicon": _make_lexicon({}),
        "topics": _make_topics({"hot": {"posts_last_7d": 30}}),
        "voice": _make_voice([]),
    }
    prev = {
        "lexicon": _make_lexicon({}),
        "topics": _make_topics({"hot": {"posts_last_7d": 10}}),
        "voice": _make_voice([]),
    }
    d = wp.diff(now, prev, anti_models=set())
    assert len(d.cadence_shifts) == 1
    assert d.cadence_shifts[0].channel == "hot"
    assert d.cadence_shifts[0].direction == "up"


def test_render_handles_zero_prev_count_without_inf_percent():
    """Channel that went 0 → N must render as 'new activity', not +inf%."""
    now = {
        "lexicon": _make_lexicon({}),
        "topics": _make_topics({"newchan": {"posts_last_7d": 20}}),
        "voice": _make_voice([]),
    }
    prev = {
        "lexicon": _make_lexicon({}),
        "topics": _make_topics({"newchan": {"posts_last_7d": 0}}),
        "voice": _make_voice([]),
    }
    d = wp.diff(now, prev, anti_models=set())
    text = wp.render(d)
    assert "inf" not in text.lower()
    assert "новая активность" in text or "0 → 20" in text


def test_park_for_review_rejects_path_traversal():
    """The week parameter flows into a filename; reject anything not YYYY-Www."""
    with pytest.raises(ValueError):
        wp.park_for_review("body", ["reason"], Path("/tmp/x"), "../../etc/passwd")
    with pytest.raises(ValueError):
        wp.park_for_review("body", ["reason"], Path("/tmp/x"), "2026/W18")


def test_park_for_review_accepts_valid_week(tmp_path):
    out = wp.park_for_review("body", ["reason"], tmp_path, "2026-W18")
    assert out.parent == tmp_path
    assert out.name == "2026-W18_pulse.md"


def test_diff_detects_hype_increase():
    anti = {"larkin"}
    now = {
        "lexicon": _make_lexicon({}),
        "topics": _make_topics({}),
        "voice": _make_voice([{
            "name": "larkin", "n_posts": 50,
            "caps_per_100w": 5.0, "bullet_share": 0.5, "listicle_share": 0.6,
        }]),
    }
    prev = {
        "lexicon": _make_lexicon({}),
        "topics": _make_topics({}),
        "voice": _make_voice([{
            "name": "larkin", "n_posts": 50,
            "caps_per_100w": 1.0, "bullet_share": 0.1, "listicle_share": 0.1,
        }]),
    }
    d = wp.diff(now, prev, anti_models=anti)
    assert d.hype is not None
    assert d.hype.direction == "UP"
    assert d.hype.hype_delta > 0


def test_judge_passes_clean_text():
    text = ("● RU Pulse #19 — 3 май 2026\n\n"
            "claude вырос на 42% за неделю.\n\n"
            "Что изменилось\n\n"
            "Я провёл анализ корпуса. " * 30 +
            "\n\nПолный отчёт: solo-lab.dev/pulse")
    ok, reasons = wp.judge(text)
    assert ok, f"unexpectedly failed: {reasons}"


def test_judge_rejects_tabu_word():
    text = "● Заголовок\n\n" + ("это revolutionary момент. " * 30)
    ok, reasons = wp.judge(text)
    assert ok is False
    assert any("tabu" in r for r in reasons)


def test_judge_rejects_exclamation():
    text = "● Заголовок\n\n" + ("это очень важно! " * 30)
    ok, reasons = wp.judge(text)
    assert ok is False
    assert any("exclamation" in r for r in reasons)


def test_judge_rejects_too_short():
    text = "● Заголовок\n\nкороткий текст."
    ok, reasons = wp.judge(text)
    assert ok is False
    assert any("word count" in r for r in reasons)


def test_judge_rejects_listicle_run():
    text = ("● Заголовок\n\n"
            "Слова чтобы пройти word count. " * 50 +
            "\n- пункт один\n- пункт два\n- пункт три\n- пункт четыре\n- пункт пять\n")
    ok, reasons = wp.judge(text)
    assert ok is False
    assert any("bullet" in r for r in reasons)


def test_render_no_prev_returns_first_run_message():
    d = wp.DiffResult(week_current="2026-W19", week_prev="—", data_ok=False)
    text = wp.render(d)
    assert "Первый запуск" in text
    assert text.startswith("<b>● RU Pulse")


def test_render_with_rising_terms():
    d = wp.DiffResult(
        week_current="2026-W19", week_prev="2026-W18",
        rising=[wp.TermDelta(term="claude", count_now=150, count_prev=50,
                             delta_pct=200.0, channels_now=24)],
        data_ok=True,
    )
    text = wp.render(d)
    assert "claude" in text
    assert "200" in text
    assert "<b>● RU Pulse" in text


def test_snapshot_and_load_roundtrip(tmp_path, monkeypatch):
    # Stub the report files so snapshot() can read them
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "lexicon_report.json").write_text(json.dumps({"per_channel": []}))
    (reports / "topics_report.json").write_text(json.dumps({"cadence": {}}))
    (reports / "voice_fingerprint.json").write_text(json.dumps({"raw": []}))

    monkeypatch.setattr(wp, "LEXICON_PATH", reports / "lexicon_report.json")
    monkeypatch.setattr(wp, "TOPICS_PATH", reports / "topics_report.json")
    monkeypatch.setattr(wp, "VOICE_PATH", reports / "voice_fingerprint.json")

    snap_dir = tmp_path / "snaps"
    data = wp.snapshot(snap_dir)
    assert data["snapshot_week"].startswith("20")
    assert "lexicon" in data and "topics" in data and "voice" in data

    # File on disk
    files = list(snap_dir.glob("*.json.gz"))
    assert len(files) == 1
    with gzip.open(files[0], "rt", encoding="utf-8") as f:
        roundtrip = json.load(f)
    assert roundtrip["snapshot_week"] == data["snapshot_week"]


def test_snapshot_pruning_keeps_only_last_n(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "lexicon_report.json").write_text(json.dumps({"per_channel": []}))
    (reports / "topics_report.json").write_text(json.dumps({"cadence": {}}))
    (reports / "voice_fingerprint.json").write_text(json.dumps({"raw": []}))

    monkeypatch.setattr(wp, "LEXICON_PATH", reports / "lexicon_report.json")
    monkeypatch.setattr(wp, "TOPICS_PATH", reports / "topics_report.json")
    monkeypatch.setattr(wp, "VOICE_PATH", reports / "voice_fingerprint.json")
    monkeypatch.setattr(wp, "KEEP_SNAPSHOTS", 3)

    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    # Pre-create 5 fake old snapshots
    for i in range(5):
        fake = snap_dir / f"2025-W{i:02d}.json.gz"
        with gzip.open(fake, "wt") as f:
            f.write("{}")

    wp.snapshot(snap_dir)
    files = sorted(snap_dir.glob("*.json.gz"))
    assert len(files) == 3, [f.name for f in files]
