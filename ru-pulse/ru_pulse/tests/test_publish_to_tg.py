"""Tests for ru_pulse.publish_to_tg — mocks urllib.request.urlopen."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import publish_to_tg as mod


class _FakeResp:
    def __init__(self, status: int, body: dict | str) -> None:
        self.status = status
        self._body = body if isinstance(body, str) else json.dumps(body)

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _ok_response(message_id: int = 1) -> _FakeResp:
    return _FakeResp(200, {"ok": True, "result": {"message_id": message_id}})


def test_send_message_happy_path() -> None:
    with patch.object(mod.urllib.request, "urlopen", return_value=_ok_response(42)) as op:
        result = mod.send_message("hello", chat_id="-100", token="t")
    assert result["ok"] is True
    assert result["result"]["message_id"] == 42
    assert op.call_count == 1
    sent = json.loads(op.call_args.args[0].data.decode("utf-8"))
    assert sent["chat_id"] == "-100"
    assert sent["parse_mode"] == "HTML"
    assert sent["disable_web_page_preview"] is True


def test_send_message_non_200_raises() -> None:
    with patch.object(mod.urllib.request, "urlopen", return_value=_FakeResp(500, "boom")):
        with pytest.raises(RuntimeError, match="500|Telegram"):
            mod.send_message("hi", chat_id="-1", token="t")


def test_send_message_ok_false_raises() -> None:
    bad = _FakeResp(200, {"ok": False, "description": "chat not found"})
    with patch.object(mod.urllib.request, "urlopen", return_value=bad):
        with pytest.raises(RuntimeError, match="chat not found|API error"):
            mod.send_message("hi", chat_id="-1", token="t")


def test_long_message_splits_into_two_calls() -> None:
    long_text = ("word " * 1200).strip()  # ~6000 chars, > 4096
    assert len(long_text) > mod.TG_LIMIT
    with patch.object(mod.urllib.request, "urlopen",
                      side_effect=[_ok_response(1), _ok_response(2)]) as op:
        mod.send_message(long_text, chat_id="-1", token="t")
    assert op.call_count == 2
    chunks = [json.loads(c.args[0].data.decode("utf-8"))["text"] for c in op.call_args_list]
    assert all(len(c) <= mod.TG_LIMIT for c in chunks)


def test_html_comments_stripped_before_send() -> None:
    text = "<!-- refined:v1 -->\n<b>real body</b>\n<!-- trailing -->"
    with patch.object(mod.urllib.request, "urlopen", return_value=_ok_response()) as op:
        mod.send_message(text, chat_id="-1", token="t")
    sent = json.loads(op.call_args.args[0].data.decode("utf-8"))["text"]
    assert "<!--" not in sent
    assert "refined:v1" not in sent
    assert "<b>real body</b>" in sent


def test_load_token_reads_via_pathlib(tmp_path: Path) -> None:
    f = tmp_path / "tok.txt"
    f.write_text("  abc:123  \n", encoding="utf-8")
    assert mod.load_token(f) == "abc:123"


def test_load_token_missing_raises_helpful(tmp_path: Path) -> None:
    missing = tmp_path / "nope.txt"
    with pytest.raises(RuntimeError, match="not found"):
        mod.load_token(missing)


def test_load_token_empty_raises(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty"):
        mod.load_token(f)


def test_load_chat_id_reads_via_pathlib(tmp_path: Path) -> None:
    f = tmp_path / "ch.json"
    f.write_text(json.dumps({"ru": {"chat_id": "-1003720942904"}}), encoding="utf-8")
    assert mod.load_chat_id("ru", f) == "-1003720942904"


def test_load_chat_id_unknown_channel_raises(tmp_path: Path) -> None:
    f = tmp_path / "ch.json"
    f.write_text(json.dumps({"ru": {"chat_id": "-1"}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not found in"):
        mod.load_chat_id("he", f)


def test_load_chat_id_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not found"):
        mod.load_chat_id("ru", tmp_path / "absent.json")


def test_empty_text_after_strip_raises() -> None:
    with pytest.raises(RuntimeError, match="empty"):
        mod.send_message("<!-- only comment -->", chat_id="-1", token="t")
