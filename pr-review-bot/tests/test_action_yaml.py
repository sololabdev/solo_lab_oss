"""Validate the action manifest and entrypoint shape.

These tests don't need a network or docker — they parse the YAML and
the bash entrypoint and assert on structure. Run via:

    pytest pr-review-bot/tests/test_action_yaml.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_action_yaml_parses():
    import yaml  # type: ignore[import-untyped]
    data = yaml.safe_load(_read(ROOT / "action.yml"))
    assert data["name"] == "Solo Lab PR Review Bot"
    assert data["runs"]["using"] == "docker"
    assert data["runs"]["image"] == "Dockerfile"


def test_action_inputs_documented():
    import yaml
    data = yaml.safe_load(_read(ROOT / "action.yml"))
    inputs = data["inputs"]
    for name in (
        "solo-lab-api-key", "review-style", "comment-mode",
        "api-endpoint", "fail-on-findings",
    ):
        assert name in inputs, f"missing input: {name}"
        assert inputs[name].get("description"), f"input {name} missing description"


def test_dockerfile_uses_alpine():
    text = _read(ROOT / "Dockerfile")
    # Must use alpine as the base for a small image; comments above FROM are fine.
    assert re.search(r"^FROM alpine", text, re.MULTILINE), \
        "Dockerfile must include `FROM alpine` for a small image"
    # gh, jq, curl, bash are required by entrypoint.sh — must be installed.
    for pkg in ("github-cli", "jq", "curl", "bash"):
        assert pkg in text, f"Dockerfile missing apk add for {pkg}"


def test_entrypoint_is_strict_bash():
    text = _read(ROOT / "entrypoint.sh")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text


def test_entrypoint_validates_inputs():
    text = _read(ROOT / "entrypoint.sh")
    # Whitelist for review-style / comment-mode must be present.
    assert re.search(r"voice\|code\|both", text)
    assert re.search(r"summary\|inline", text)


def test_entrypoint_never_fails_on_api_outage():
    """Defensive default: API errors must not break the user's workflow."""
    text = _read(ROOT / "entrypoint.sh")
    # The two non-200 branches both exit 0.
    assert text.count("never fail the host workflow") >= 1


def test_readme_has_install_snippet():
    text = _read(ROOT / "README.md")
    assert "uses: sololabdev/pr-review-bot@v1" in text
    assert "pull-requests: write" in text


def test_readme_is_honest_about_v1_scope():
    text = _read(ROOT / "README.md")
    # The "Honest scope" section must exist and call out v1 vs v2.
    assert "Honest scope" in text
    assert "v2" in text
    assert "code review" in text.lower()


def test_examples_present():
    assert (ROOT / "examples" / "sample-review-comment.md").exists()
    assert (ROOT / "examples" / "clean-pr.md").exists()
    assert (ROOT / "examples" / "workflow.yml").exists()


def test_api_doc_present():
    text = _read(ROOT / "docs" / "api.md")
    # Both protocol shapes documented.
    assert "POST {api-endpoint}" in text
    assert "review_style" in text
    assert "comment_mode" in text
    assert '"ok":       true' in text or '"ok": true' in text
