"""Tests for voice_fingerprint pure functions — no DB, no I/O."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import voice_fingerprint as vf


def test_post_features_handles_empty_string():
    f = vf.post_features("")
    assert f["chars"] == 0
    # n_words / n_sent are min-clamped to 1 to avoid div-by-zero
    assert f["words"] == 1
    assert f["sentences"] == 1
    assert f["exclam"] == 0


def test_post_features_handles_none():
    """post_features should treat None as empty (defensive)."""
    f = vf.post_features(None)
    assert f["chars"] == 0


def test_post_features_counts_exclam_question():
    f = vf.post_features("Wow! Really? Amazing!")
    assert f["exclam"] == 2
    assert f["question"] == 1


def test_post_features_emoji_url_hashtag():
    f = vf.post_features("Cool 🚀 link https://x.com #tag #vibe")
    assert f["emoji_count"] >= 1
    assert f["url_count"] == 1
    assert f["hashtag_count"] == 2


def test_post_features_caps_words():
    """ALL-CAPS words longer than 1 char count; single-letter ALL-CAPS don't."""
    f = vf.post_features("This is URGENT and BIG news but I should not count")
    # URGENT, BIG → 2 caps words; "I" is single-char so excluded
    assert f["caps_words"] >= 2


def test_post_features_long_post_threshold():
    short = vf.post_features("a" * 100)
    long_ = vf.post_features("a" * 900)
    assert short["long_post"] == 0
    assert long_["long_post"] == 1


def test_per_channel_empty_posts_returns_minimal():
    fp = vf.per_channel("dead_channel", [])
    assert fp["name"] == "dead_channel"
    assert fp["n_posts"] == 0
    assert "exclam_per_100w" not in fp


def test_per_channel_aggregates_metrics():
    posts = [
        "Wow! Amazing!",
        "Just text without much.",
        "Another!!! post here.",
    ]
    fp = vf.per_channel("ch1", posts)
    assert fp["n_posts"] == 3
    assert fp["exclam_per_100w"] > 0
    assert "avg_words" in fp
    assert "long_post_share" in fp


def test_fingerprint_distance_zero_for_identical():
    a = {"x": 1.0, "y": 0.5}
    b = {"x": 1.0, "y": 0.5}
    assert vf.fingerprint_distance(a, b, ["x", "y"]) == 0.0


def test_fingerprint_distance_euclidean():
    a = {"x": 0.0, "y": 0.0}
    b = {"x": 3.0, "y": 4.0}
    # sqrt(9+16) = 5
    assert vf.fingerprint_distance(a, b, ["x", "y"]) == pytest.approx(5.0)


def test_fingerprint_distance_handles_missing_keys():
    """Missing key on one side defaults to 0."""
    a = {"x": 1.0}
    b = {"y": 1.0}
    # both contribute 1 each → sqrt(2)
    assert vf.fingerprint_distance(a, b, ["x", "y"]) == pytest.approx(2 ** 0.5)


def test_normalize_corpus_min_max_to_unit_interval():
    chs = [
        {"name": "a", "n_posts": 10, "score": 0.0},
        {"name": "b", "n_posts": 10, "score": 5.0},
        {"name": "c", "n_posts": 10, "score": 10.0},
    ]
    out = vf.normalize_corpus(chs, ["score"])
    assert out[0]["score"] == 0.0
    assert out[1]["score"] == 0.5
    assert out[2]["score"] == 1.0


def test_normalize_corpus_skips_empty_channels():
    """Channels with n_posts=0 should not influence min/max and stay at 0."""
    chs = [
        {"name": "live", "n_posts": 10, "score": 4.0},
        {"name": "dead", "n_posts": 0, "score": 999.0},  # outlier ignored
        {"name": "live2", "n_posts": 5, "score": 8.0},
    ]
    out = vf.normalize_corpus(chs, ["score"])
    # min=4, max=8, dead stays 0 because n_posts==0
    assert out[0]["score"] == 0.0
    assert out[1]["score"] == 0
    assert out[2]["score"] == 1.0


def test_normalize_corpus_all_equal_no_div_zero():
    chs = [
        {"name": "a", "n_posts": 10, "score": 3.0},
        {"name": "b", "n_posts": 10, "score": 3.0},
    ]
    out = vf.normalize_corpus(chs, ["score"])
    # rng forced to 1.0; (3-3)/1 = 0 for both
    assert out[0]["score"] == 0.0
    assert out[1]["score"] == 0.0
