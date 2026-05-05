"""Tests for the lexicon analyzer — pure functions, no DB."""
from __future__ import annotations

import sys
from pathlib import Path

RESEARCH_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_DIR))

from ru_pulse import analyze


def test_tokenize_handles_mixed_cyr_lat_digits():
    toks = analyze.tokenize("Деплой OpenAI claude-code на 8080")
    assert "деплой" in toks
    assert "openai" in toks
    assert "claude-code" in toks
    assert "8080" in toks


def test_is_latin_vs_cyrillic():
    assert analyze.is_latin("openai")
    assert not analyze.is_latin("деплой")
    assert analyze.is_cyrillic("деплой")
    assert not analyze.is_cyrillic("openai")


def test_is_stopword():
    assert analyze.is_stopword("и")
    assert analyze.is_stopword("the")
    assert not analyze.is_stopword("деплой")
    assert not analyze.is_stopword("claude")


def test_post_metrics_basic_counts():
    text = "Привет! Это пост. У меня есть ссылка https://example.com #tag"
    m = analyze.post_metrics(text)
    assert m["url_count"] == 1
    assert m["hashtag_count"] == 1
    assert m["exclam_count"] == 1
    assert m["sentences"] >= 2
    assert m["tokens"] > 0


def test_post_metrics_empty_text():
    m = analyze.post_metrics("")
    assert m["tokens"] == 0
    assert m["loanword_share"] == 0.0
    assert m["sentences"] == 1  # max(1, ...)


def test_post_metrics_loanword_share():
    text = "claude openai gpt code деплой"
    m = analyze.post_metrics(text)
    # 4 latin + 1 cyrillic content tokens. Plus word splitting may include numbers.
    assert m["tokens_lat"] >= 4
    assert m["tokens_cyr"] >= 1
    assert m["loanword_share"] > 0


def test_n_grams_returns_counter():
    counter = analyze.n_grams(["a", "b", "c", "a", "b"], 2)
    assert counter[("a", "b")] == 2
    assert counter[("b", "c")] == 1


def test_jaccard_identical_sets():
    assert analyze.jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint_sets():
    assert analyze.jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial_overlap():
    j = analyze.jaccard({"a", "b", "c"}, {"b", "c", "d"})
    assert j == 2 / 4  # |intersection|=2, |union|=4


def test_jaccard_empty_sets():
    assert analyze.jaccard(set(), set()) == 0.0


def test_per_channel_stats_synthetic():
    posts = [
        ("2026-01-01T00:00:00+00:00", "Привет! Я тестирую claude code."),
        ("2026-01-02T00:00:00+00:00", "Сделал embedding для RAG."),
        ("2026-01-03T00:00:00+00:00", "Это длинный пост про OpenAI и Anthropic."),
    ]
    stats = analyze.per_channel_stats("test_ch", posts, top_k=10)
    assert stats["name"] == "test_ch"
    assert stats["n_posts"] == 3
    assert stats["n_tokens"] > 0
    assert 0 <= stats["loanword_share"] <= 1
    assert 0 <= stats["code_switching_rate"] <= 1
    assert isinstance(stats["top_cyr"], list)
    assert isinstance(stats["top_lat"], list)


def test_per_channel_stats_empty_posts():
    stats = analyze.per_channel_stats("empty", [])
    assert stats == {"name": "empty", "n_posts": 0}
