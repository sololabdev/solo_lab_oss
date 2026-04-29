"""Unit tests for the pure (Playwright-free) functions in structural_judge.

The async path needs Chromium and is exercised by the example; these tests
pin the synchronous logic that doesn't require a browser."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from structural_judge import _parse_px, detect_issues, score_from_issues


def test_parse_px_handles_normal_keyword() -> None:
    assert _parse_px("normal") == 0
    assert _parse_px("normal", default=24) == 24


def test_parse_px_handles_auto_and_empty() -> None:
    assert _parse_px("auto") == 0
    assert _parse_px("") == 0
    assert _parse_px(None) == 0


def test_parse_px_extracts_leading_integer() -> None:
    assert _parse_px("48px") == 48
    assert _parse_px("12.5px") == 12  # leading int only


def test_score_from_issues_clean_layout_scores_high() -> None:
    score = score_from_issues(issues=[], elements_count=8)
    assert 0.85 <= score <= 1.0


def test_score_from_issues_overflow_penalises() -> None:
    clean = score_from_issues(issues=[], elements_count=8)
    overflow = score_from_issues(
        issues=["'.headline' extends 12px past right edge"],
        elements_count=8,
    )
    assert overflow < clean
    assert overflow == 0.95  # 1.0 minus single non-overlap-pixel issue × 0.05


def test_score_from_issues_overlap_penalises() -> None:
    clean = score_from_issues(issues=[], elements_count=8)
    overlap = score_from_issues(
        issues=["OVERLAP: '.headline' and '.deck' overlap 40x30px"],
        elements_count=8,
    )
    assert overlap < clean


def _el(uid: int, selector: str, x: int, y: int, w: int, h: int,
        text: str = "hi", anchor: str = "top") -> dict:
    return {
        "uid": uid, "selector": selector, "index": 0, "text": text,
        "x": x, "y": y, "w": w, "h": h,
        "right": x + w, "bottom": y + h,
        "font_size": "48px", "line_height": "normal", "color": "black",
        "position_kind": "absolute",
        "css_top": f"{y}px", "css_bottom": "auto",
        "anchor": anchor, "ancestor_uids": [],
    }


def test_detect_issues_clean_layout_has_no_issues() -> None:
    layout = {
        "elements": [_el(0, ".headline", 50, 50, 980, 100)],
        "canvas": {"width": 1080, "height": 1080},
    }
    issues, fixes = detect_issues(layout, 1080, 1080)
    assert isinstance(issues, list)
    assert isinstance(fixes, list)
    assert issues == []


def test_detect_issues_flags_overflow_past_right_edge() -> None:
    layout = {
        "elements": [_el(0, ".headline", 50, 50, 1100, 100)],  # x+w=1150 > 1080
        "canvas": {"width": 1080, "height": 1080},
    }
    issues, _ = detect_issues(layout, 1080, 1080)
    assert any("right edge" in i for i in issues)
