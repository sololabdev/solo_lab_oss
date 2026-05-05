"""Unit tests for cache_lab.py — usage extraction across providers,
cost computation, and budget safety stop.

External calls (urllib to OpenRouter) are NOT exercised — the lab
script's network path is integration-tested by the live benchmark.
These tests cover the pure-Python normalization logic that was the
source of past breakage when provider response shapes drifted.
"""
from __future__ import annotations

import json
import pathlib

import cache_lab


def _anthropic_response(prompt: int, completion: int,
                       cache_read: int = 0, cache_write: int = 0,
                       cost: float = 0.0) -> dict:
    return {
        "provider": "Anthropic",
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost": cost,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
            "prompt_tokens_details": {
                "cached_tokens": cache_read,
                "cache_write_tokens": cache_write,
            },
        },
    }


def _openai_response(prompt: int, completion: int,
                    cached: int = 0, cost: float = 0.0) -> dict:
    return {
        "provider": "OpenAI",
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost": cost,
            "prompt_tokens_details": {
                "cached_tokens": cached,
                "cache_write_tokens": 0,
            },
        },
    }


def _gemini_response(prompt: int, completion: int,
                    cached: int = 0, cost: float = 0.0) -> dict:
    return {
        "provider": "Google",
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cost": cost,
            "prompt_tokens_details": {
                "cached_tokens": cached,
                "cache_write_tokens": 0,
            },
        },
    }


def test_extract_usage_anthropic_shape() -> None:
    """Anthropic-style: cache_read_input_tokens at top-level usage."""
    resp = _anthropic_response(prompt=6000, completion=200,
                               cache_read=5928, cost=0.0013)
    out = cache_lab._extract_usage(resp)
    assert out["input_tokens"] == 6000
    assert out["output_tokens"] == 200
    assert out["cache_read_input_tokens"] == 5928
    assert out["cache_creation_input_tokens"] == 0
    assert out["cost_usd"] == 0.0013
    assert out["provider"] == "Anthropic"


def test_extract_usage_openai_shape() -> None:
    """OpenAI-style: cached_tokens nested in prompt_tokens_details only."""
    resp = _openai_response(prompt=6000, completion=200, cached=4096, cost=0.0089)
    out = cache_lab._extract_usage(resp)
    assert out["input_tokens"] == 6000
    assert out["cache_read_input_tokens"] == 4096
    assert out["cache_creation_input_tokens"] == 0
    assert out["cost_usd"] == 0.0089
    assert out["provider"] == "OpenAI"


def test_extract_usage_gemini_shape() -> None:
    """Gemini routed via OpenRouter — should hit the same nested field."""
    resp = _gemini_response(prompt=5772, completion=180, cached=5500, cost=0.000245)
    out = cache_lab._extract_usage(resp)
    assert out["input_tokens"] == 5772
    assert out["cache_read_input_tokens"] == 5500
    assert out["provider"] == "Google"


def test_extract_usage_no_cache_block() -> None:
    """Provider that omits cache fields entirely — should default to 0."""
    resp = {
        "provider": "AkashML",
        "usage": {"prompt_tokens": 500, "completion_tokens": 50, "cost": 0.00005},
    }
    out = cache_lab._extract_usage(resp)
    assert out["cache_read_input_tokens"] == 0
    assert out["cache_creation_input_tokens"] == 0
    assert out["input_tokens"] == 500


def test_compute_cost_no_cache() -> None:
    """No cache: actual cost equals full no-cache hypothetical, savings = 0."""
    cfg = cache_lab.MODELS["haiku"]
    # 6000 input × $1/M = $0.006; 200 output × $5/M = $0.001 -> $0.007
    usage = {"input_tokens": 6000, "output_tokens": 200,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "cost_usd": 0.007}
    cost = cache_lab._compute_cost(usage, cfg)
    assert cost["actual_cost_usd"] == 0.007
    assert cost["no_cache_cost_usd"] == 0.007
    assert cost["savings_pct"] == 0.0


def test_compute_cost_full_cache_hit() -> None:
    """Full cache hit on input — actual much smaller than hypothetical."""
    cfg = cache_lab.MODELS["haiku"]
    # All 6000 input came from cache -> charged at cache_read 0.10/M = $0.0006
    # plus output 200 × $5/M = $0.001  -> total $0.0016
    usage = {"input_tokens": 6000, "output_tokens": 200,
             "cache_read_input_tokens": 5928, "cache_creation_input_tokens": 0,
             "cost_usd": 0.0016}
    cost = cache_lab._compute_cost(usage, cfg)
    # No-cache hypothetical: 6000×$1/M + 200×$5/M = $0.007
    assert cost["no_cache_cost_usd"] == 0.007
    assert cost["actual_cost_usd"] == 0.0016
    # Savings = 0.0054 -> 77.1%
    assert 75.0 < cost["savings_pct"] < 80.0


def test_compute_cost_zero_input_safe() -> None:
    """Edge case: 0 input tokens -> no division by zero."""
    cfg = cache_lab.MODELS["haiku"]
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "cost_usd": 0.0}
    cost = cache_lab._compute_cost(usage, cfg)
    assert cost["actual_cost_usd"] == 0.0
    assert cost["savings_pct"] == 0.0


def test_budget_tracker_records_and_caps(tmp_path: pathlib.Path) -> None:
    """Budget tracker persists spend and refuses calls past cap."""
    p = tmp_path / "budget.json"
    bt = cache_lab.BudgetTracker(path=p, cap_usd=1.0)
    assert bt.total() == 0.0
    assert bt.can_spend(0.5) is True

    bt.record(0.30)
    bt.record(0.40)
    assert abs(bt.total() - 0.70) < 1e-9
    assert bt.can_spend(0.20) is True
    assert bt.can_spend(0.50) is False  # would exceed cap

    # State persisted on disk
    state = json.loads(p.read_text())
    assert state["calls"] == 2
    assert abs(state["total_spent_usd"] - 0.70) < 1e-9


def test_budget_tracker_reset(tmp_path: pathlib.Path) -> None:
    """Reset clears spend and call count."""
    p = tmp_path / "budget.json"
    bt = cache_lab.BudgetTracker(path=p, cap_usd=14.0)
    bt.record(5.0)
    assert bt.total() == 5.0
    bt.reset()
    assert bt.total() == 0.0
    assert bt.state["calls"] == 0


def test_models_dict_complete() -> None:
    """All 10 brief-mandated models present with required fields."""
    expected = {
        "haiku", "sonnet", "opus",
        "gpt4o-mini", "gpt4o", "gpt55",
        "gemini-flash", "gemini-pro",
        "deepseek", "llama",
    }
    assert set(cache_lab.MODELS.keys()) == expected
    for key, cfg in cache_lab.MODELS.items():
        assert "slug" in cfg, f"{key} missing slug"
        assert "input_per_m" in cfg
        assert "output_per_m" in cfg
        assert "cache_type" in cfg
        assert cfg["cache_type"] in ("explicit", "implicit", "varies")
