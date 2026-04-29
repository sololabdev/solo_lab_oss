"""Unit tests for benchmark_opus_47.auto_score_needle().

The boundary regex for short numeric tokens is the part most likely to
regress silently — these tests pin its behaviour."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from benchmark_opus_47 import auto_score_needle


def _q(scorer_keywords: list[str], forbidden: list[str] | None = None) -> dict:
    return {"scorer_keywords": scorer_keywords, "forbidden_keywords": forbidden or []}


def test_short_numeric_exact_match_word_boundary() -> None:
    assert auto_score_needle("The value is 30.", _q(["30"])) == "correct"


def test_short_numeric_does_not_match_inside_longer_number() -> None:
    # 300 should not be a hit for keyword '30' — that was the false-positive
    # the word-boundary regex is meant to prevent.
    assert auto_score_needle("Threshold is 300 ms.", _q(["30"])) == "wrong"


def test_long_numeric_substring_match() -> None:
    # 4-char-plus numerics use plain substring; '1080' inside '10801920' counts.
    assert auto_score_needle("Resolution 1080x1920.", _q(["1080"])) == "correct"


def test_partial_when_some_but_not_all_keywords_hit() -> None:
    res = auto_score_needle("eleven_v3 only.", _q(["eleven_v3", "api.elevenlabs.io"]))
    assert res == "partial"


def test_forbidden_keyword_overrides_to_wrong() -> None:
    res = auto_score_needle(
        "Yes, healer.py imports it directly.",
        _q(["pipeline.py"], forbidden=["healer"]),
    )
    assert res == "wrong"


def test_case_insensitive_match() -> None:
    assert auto_score_needle("THE ANSWER IS Eleven_V3", _q(["eleven_v3"])) == "correct"


def test_dotted_number_short_form_matches() -> None:
    # "1.08" is treated as numeric short token (length 4 incl. dot, but
    # `.replace(".","").isdigit()` returns True and len <=3 after strip is 3).
    assert auto_score_needle("Zoom end 1.08.", _q(["1.08"])) == "correct"
