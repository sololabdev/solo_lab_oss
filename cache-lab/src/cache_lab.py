#!/usr/bin/env python3
"""Cache lab — measure real prompt-cache hit rate + savings across
production LLMs via OpenRouter. Stdlib-only.

Why: marketing claims 90% cache discount across providers; this script
verifies the claim by sending identical stable-prefix calls and recording
what each provider's `usage` block actually says.

OpenRouter normalizes all providers into:
    usage.prompt_tokens
    usage.completion_tokens
    usage.cost                                 -- real billed amount
    usage.prompt_tokens_details.cached_tokens  -- cache reads
    usage.prompt_tokens_details.cache_write_tokens  -- cache writes
    usage.cost_details.upstream_inference_cost
    plus provider, model_returned

We use `usage.cost` as ground truth for actual cost, and compute a
no-cache hypothetical from per-M rates for the savings %.

Usage:
    python3 cache_lab.py --model haiku --runs 10
    python3 cache_lab.py --all --runs 30
    python3 cache_lab.py --model opus --runs 10 --json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

OR_URL = "https://openrouter.ai/api/v1/chat/completions"
ROOT = pathlib.Path(__file__).resolve().parent
RECEIPTS_PATH = ROOT / "cache_lab_receipts.json"
CALLS_LOG_PATH = ROOT / "cache_lab_calls.jsonl"
BUDGET_PATH = ROOT / "cache_lab_budget.json"
DEFAULT_BUDGET_CAP_USD = 14.00  # safety margin under $15 hard cap
SINGLE_CALL_ABORT_USD = 0.50    # abort if a single call costs > this

# Per-million-token rates verified from OpenRouter /api/v1/models 2026-05-05.
# Anthropic + Gemini have explicit cache_control support; OpenAI/DeepSeek/Llama
# rely on implicit prefix caching (when their upstream supports it).
# `force_provider`: pin to native upstream so cache_control isn't dropped by a
# re-router (e.g. Anthropic -> Bedrock would otherwise be auto-selected).
MODELS: dict[str, dict] = {
    "haiku": {
        "slug": "anthropic/claude-haiku-4.5",
        "input_per_m": 1.00,
        "output_per_m": 5.00,
        "cache_creation_per_m": 1.25,
        "cache_read_per_m": 0.10,
        "use_cache_control": True,
        "force_provider": "Anthropic",
        "cache_type": "explicit",
    },
    "sonnet": {
        "slug": "anthropic/claude-sonnet-4.6",
        "input_per_m": 3.00,
        "output_per_m": 15.00,
        "cache_creation_per_m": 3.75,
        "cache_read_per_m": 0.30,
        "use_cache_control": True,
        "force_provider": "Anthropic",
        "cache_type": "explicit",
    },
    "opus": {
        "slug": "anthropic/claude-opus-4.7",
        "input_per_m": 5.00,
        "output_per_m": 25.00,
        "cache_creation_per_m": 6.25,
        "cache_read_per_m": 0.50,
        "use_cache_control": True,
        "force_provider": "Anthropic",
        "cache_type": "explicit",
    },
    "gpt4o-mini": {
        "slug": "openai/gpt-4o-mini",
        "input_per_m": 0.15,
        "output_per_m": 0.60,
        "cache_creation_per_m": 0.0,
        "cache_read_per_m": 0.075,
        "use_cache_control": False,
        "force_provider": None,
        "cache_type": "implicit",
    },
    "gpt4o": {
        "slug": "openai/gpt-4o",
        "input_per_m": 2.50,
        "output_per_m": 10.00,
        "cache_creation_per_m": 0.0,
        "cache_read_per_m": 1.25,
        "use_cache_control": False,
        "force_provider": None,
        "cache_type": "implicit",
    },
    "gpt55": {
        "slug": "openai/gpt-5.5",
        "input_per_m": 5.00,
        "output_per_m": 30.00,
        "cache_creation_per_m": 0.0,
        "cache_read_per_m": 0.50,
        "use_cache_control": False,
        "force_provider": None,
        "cache_type": "implicit",
    },
    "gemini-flash": {
        "slug": "google/gemini-2.5-flash",
        "input_per_m": 0.30,
        "output_per_m": 2.50,
        "cache_creation_per_m": 0.0833,
        "cache_read_per_m": 0.03,
        "use_cache_control": True,
        "force_provider": "Google",
        "cache_type": "explicit",
    },
    "gemini-pro": {
        "slug": "google/gemini-2.5-pro",
        "input_per_m": 1.25,
        "output_per_m": 10.00,
        "cache_creation_per_m": 0.375,
        "cache_read_per_m": 0.125,
        "use_cache_control": True,
        "force_provider": "Google",
        "cache_type": "explicit",
    },
    "deepseek": {
        "slug": "deepseek/deepseek-chat-v3.1",
        "input_per_m": 0.15,
        "output_per_m": 0.75,
        "cache_creation_per_m": 0.0,
        "cache_read_per_m": 0.0375,  # ≈75% off if upstream supports it
        "use_cache_control": False,
        # OR has no native "DeepSeek" upstream for this slug — only 3rd-party hosts
        # (sambanova, deepinfra, chutes, novita, fireworks, together…).
        # Pinning to `fireworks` because it has documented prompt caching.
        "force_provider": "Fireworks",
        "cache_type": "implicit",
    },
    "llama": {
        "slug": "meta-llama/llama-3.3-70b-instruct",
        "input_per_m": 0.10,
        "output_per_m": 0.32,
        "cache_creation_per_m": 0.0,
        "cache_read_per_m": 0.10,  # no cache on most upstreams; assume no discount
        "use_cache_control": False,
        "force_provider": None,
        "cache_type": "varies",
    },
}


_BRAND_HEADER = (
    "You are a brand-voice editorial judge for Solo Lab, an RU-language "
    "Telegram channel for solo founders in relocation. Your job is to "
    "evaluate caption drafts against a strict brand book and return a "
    "JSON verdict.\n\n"
    "BRAND VOICE RULES:\n"
    "- No hype words (revolutionary, transformative, game-changer, "
    "disrupt, cutting-edge)\n"
    "- No hedge phrases (Привет, друзья / на мой взгляд / как мне кажется)\n"
    "- No greeting the crowd\n"
    "- Pillar marker (■▲●◆▶) at line 1 — exactly one\n"
    "- Numbers > vibes — every claim traces to a receipt\n"
    "- First-person builder voice (я, попробовал, сломал)\n"
    "- Анти-influencer tone\n\n"
    "CONTENT PILLARS:\n"
    "- ■ STACK — what's in the stack, replaced with what, real cost\n"
    "- ▲ BUILD — what I built this week, code, numbers\n"
    "- ● SIGNAL — what's important in EN AI scene for RU readers\n"
    "- ◆ RELOCATE — banking, taxes, OCR, relocant-stack\n"
    "- ▶ PLAYBOOK — drop-in setup with JSON workflow\n\n"
    "CONTEXT FILLER (mimicking long stable prefix):\n"
)

_LOREM_A = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
_LOREM_B = "Sed ut perspiciatis unde omnis iste natus error sit. "
_FILLER_NOTE = ("\nThis prefix is repeated to test caching behavior. The "
                "system prompt above is what defines brand voice. Below the "
                "prefix, only the user message varies between calls.\n")


def build_system_prompt(target_tokens: int = 5772) -> str:
    """Build a stable system prompt at approximately target token count.

    Uses ~4 chars/token heuristic and pads with alternating lorem blocks.
    For honest scaling tests across 5K / 30K / 100K prefix sizes.
    """
    base = _BRAND_HEADER
    target_chars = target_tokens * 4
    # First fill: enough lorem to approach target
    a_repeats = max(1, (target_chars - len(base) - len(_FILLER_NOTE)) // (
        len(_LOREM_A) + len(_LOREM_B)
    ))
    return base + (_LOREM_A * a_repeats) + _FILLER_NOTE + (_LOREM_B * a_repeats)


# Default ~5,772-token stable system prompt — keeps prior runs reproducible.
STABLE_SYSTEM_PROMPT = build_system_prompt(5772)

USER_MESSAGES = [
    "Evaluate: «■ STACK · 2026-05-05\n\nDocker + cron + postgres за $4.50/мес».",
    "Evaluate: «▲ BUILD · 2026-05-06\n\nVoice gen pipeline 200 LOC».",
    "Evaluate: «● SIGNAL · 2026-05-07\n\nGemini 3.0 released сегодня».",
    "Evaluate: «◆ RELOCATE · 2026-05-08\n\nWise vs Revolut для релоканта».",
    "Evaluate: «▶ PLAYBOOK · 2026-05-09\n\nGmail digest за 15 минут».",
    "Evaluate: «Эй друзья! REVOLUTIONARY новый AI-tool, GAME CHANGER».",
    "Evaluate: «■ STACK\n\nПерешёл с Hetzner на Hostinger, save $8/mo».",
    "Evaluate: «▲ BUILD\n\nffmpeg pipeline 230 LOC, 7 MP4 за 8 минут».",
    "Evaluate: «● SIGNAL\n\nПрочитал RULER paper про long context».",
    "Evaluate: «◆ RELOCATE\n\nОсек мурше в Израиле — ₪400/мес бухгалтер».",
]


# ---------- key + budget helpers ----------

def _load_openrouter_key() -> str:
    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key:
        return env_key.strip()
    raise RuntimeError("OPENROUTER_API_KEY env var missing")


class BudgetTracker:
    """Persists cumulative spend and refuses calls that would exceed cap."""

    def __init__(self, path: pathlib.Path = BUDGET_PATH,
                 cap_usd: float = DEFAULT_BUDGET_CAP_USD) -> None:
        self.path = path
        self.cap = cap_usd
        if path.exists():
            self.state = json.loads(path.read_text())
        else:
            self.state = {"total_spent_usd": 0.0, "calls": 0,
                          "started": int(time.time())}
            self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2))

    def can_spend(self, est_usd: float) -> bool:
        return self.state["total_spent_usd"] + est_usd <= self.cap

    def record(self, actual_usd: float) -> None:
        self.state["total_spent_usd"] = round(
            self.state["total_spent_usd"] + actual_usd, 6
        )
        self.state["calls"] += 1
        self.state["updated"] = int(time.time())
        self._save()

    def total(self) -> float:
        return self.state["total_spent_usd"]

    def reset(self) -> None:
        self.state = {"total_spent_usd": 0.0, "calls": 0,
                      "started": int(time.time())}
        self._save()


# ---------- API call ----------

def _call_with_cache(model_cfg: dict, system: str, user: str, api_key: str,
                     timeout: int = 90) -> dict:
    """Call OpenRouter with explicit prompt caching where the model supports it."""
    if model_cfg.get("use_cache_control"):
        system_content = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]
    else:
        system_content = system

    payload = {
        "model": model_cfg["slug"],
        "max_tokens": 200,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user},
        ],
        "usage": {"include": True},
    }
    if model_cfg.get("force_provider"):
        payload["provider"] = {"only": [model_cfg["force_provider"]],
                               "allow_fallbacks": False}

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OR_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://solo-lab.dev",
            "X-Title": "cache-lab",
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    elapsed_ms = int((time.time() - t0) * 1000)
    return {"response": data, "elapsed_ms": elapsed_ms}


def _extract_usage(response: dict) -> dict:
    """Normalize usage shape across providers via OpenRouter's unified format."""
    usage = response.get("usage", {}) or {}
    details = usage.get("prompt_tokens_details") or {}

    cache_read = (
        usage.get("cache_read_input_tokens", 0)
        or details.get("cached_tokens", 0)
        or 0
    )
    cache_write = (
        usage.get("cache_creation_input_tokens", 0)
        or details.get("cache_write_tokens", 0)
        or details.get("cached_tokens_write", 0)
        or 0
    )
    return {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
        "cost_usd": usage.get("cost", 0.0),
        "provider": response.get("provider", "unknown"),
    }


def _compute_cost(usage: dict, model_cfg: dict) -> dict:
    """Real cost from OR's `usage.cost`; no-cache hypothetical from per-M rates.

    Hypothetical: if every input token were billed at base rate (no cache),
    plus output at output rate. That's the "no-cache" world we're saving from.
    """
    inp = usage["input_tokens"]
    out = usage["output_tokens"]
    actual = float(usage["cost_usd"])

    no_cache_total = (
        inp * model_cfg["input_per_m"] / 1_000_000
        + out * model_cfg["output_per_m"] / 1_000_000
    )
    savings = no_cache_total - actual
    savings_pct = (
        100 * savings / no_cache_total if no_cache_total > 0 else 0.0
    )
    return {
        "actual_cost_usd": round(actual, 6),
        "no_cache_cost_usd": round(no_cache_total, 6),
        "savings_usd": round(savings, 6),
        "savings_pct": round(savings_pct, 1),
    }


def _append_call_log(row: dict) -> None:
    """Crash-safe per-call append to JSONL."""
    with CALLS_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------- run ----------

def run_lab(model_key: str, runs: int, budget: BudgetTracker,
            sleep_s: float = 0.5, system_prompt: str | None = None,
            provider_pin: str | None = None) -> dict:
    """Run N calls against one model.

    Args:
        system_prompt: override stable system prompt (use build_system_prompt for size scaling)
        provider_pin: override the model's force_provider for this run only
    """
    if model_key not in MODELS:
        raise ValueError(f"unknown model: {model_key}")
    model_cfg = dict(MODELS[model_key])  # shallow copy so we can override per-run
    if provider_pin is not None:
        # Empty string clears the pin; non-empty replaces it
        model_cfg["force_provider"] = provider_pin or None
    api_key = _load_openrouter_key()
    sys_prompt = system_prompt if system_prompt is not None else STABLE_SYSTEM_PROMPT

    results: list[dict] = []
    aborted = False
    for i in range(runs):
        if not budget.can_spend(0.10):  # 10c headroom per call
            print(f"[{model_key}] BUDGET CAP — abort at run {i+1}/{runs}, "
                  f"total=${budget.total():.4f}", file=sys.stderr)
            aborted = True
            break

        user_msg = USER_MESSAGES[i % len(USER_MESSAGES)]
        try:
            call = _call_with_cache(model_cfg, sys_prompt, user_msg, api_key)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8")[:300]
            print(f"[{model_key} call {i+1}] HTTP {exc.code}: {err_body}",
                  file=sys.stderr)
            results.append({"call": i + 1, "error": f"HTTP {exc.code}: {err_body}"})
            time.sleep(sleep_s)
            continue
        except urllib.error.URLError as exc:
            print(f"[{model_key} call {i+1}] URL error: {exc}", file=sys.stderr)
            results.append({"call": i + 1, "error": f"URL: {exc}"})
            time.sleep(sleep_s)
            continue
        except (TimeoutError, OSError) as exc:
            print(f"[{model_key} call {i+1}] net error: {exc}", file=sys.stderr)
            results.append({"call": i + 1, "error": f"net: {exc}"})
            time.sleep(sleep_s)
            continue

        usage = _extract_usage(call["response"])
        cost = _compute_cost(usage, model_cfg)

        if cost["actual_cost_usd"] > SINGLE_CALL_ABORT_USD:
            print(f"[{model_key} call {i+1}] SAFETY STOP — single call "
                  f"${cost['actual_cost_usd']:.4f} > ${SINGLE_CALL_ABORT_USD}",
                  file=sys.stderr)
            results.append({"call": i + 1, "error": "single-call abort",
                            **usage, **cost})
            budget.record(cost["actual_cost_usd"])
            aborted = True
            break

        budget.record(cost["actual_cost_usd"])
        row = {
            "call": i + 1,
            "model_key": model_key,
            "slug": model_cfg["slug"],
            "ts": int(time.time()),
            "elapsed_ms": call["elapsed_ms"],
            "user_msg_preview": user_msg[:50],
            **usage,
            **cost,
        }
        results.append(row)
        _append_call_log(row)

        print(
            f"[{model_key} {i+1:2d}] {call['elapsed_ms']:5d}ms  "
            f"in={usage['input_tokens']:>6} "
            f"cache_w={usage['cache_creation_input_tokens']:>6} "
            f"cache_r={usage['cache_read_input_tokens']:>6} "
            f"out={usage['output_tokens']:>4} "
            f"prov={usage['provider']:14s} "
            f"act=${cost['actual_cost_usd']:.5f} "
            f"save={cost['savings_pct']:>5.1f}% "
            f"[budget=${budget.total():.4f}]",
            file=sys.stderr,
        )
        time.sleep(sleep_s)

    valid = [r for r in results if "error" not in r]
    total_cache_r = sum(r["cache_read_input_tokens"] for r in valid)
    total_cache_w = sum(r["cache_creation_input_tokens"] for r in valid)
    total_input = sum(r["input_tokens"] for r in valid)
    total_actual = sum(r["actual_cost_usd"] for r in valid)
    total_no_cache = sum(r["no_cache_cost_usd"] for r in valid)

    aggregate = {
        "model_key": model_key,
        "model": model_cfg["slug"],
        "cache_type": model_cfg["cache_type"],
        "force_provider": model_cfg.get("force_provider"),
        "runs_requested": runs,
        "runs_succeeded": len(valid),
        "aborted": aborted,
        "total_input_tokens": total_input,
        "total_cache_creation_tokens": total_cache_w,
        "total_cache_read_tokens": total_cache_r,
        "cache_hit_rate_pct": round(
            100 * total_cache_r / total_input, 1
        ) if total_input > 0 else 0,
        "total_actual_cost_usd": round(total_actual, 6),
        "total_no_cache_hypothetical_usd": round(total_no_cache, 6),
        "total_savings_usd": round(total_no_cache - total_actual, 6),
        "total_savings_pct": round(
            100 * (total_no_cache - total_actual) / total_no_cache, 1
        ) if total_no_cache > 0 else 0,
        "system_prompt_token_estimate": len(sys_prompt) // 4,
        "provider_pin_override": provider_pin,
        "results": results,
    }
    return aggregate


def _save_summary(agg: dict) -> None:
    existing = []
    if RECEIPTS_PATH.exists():
        existing = json.loads(RECEIPTS_PATH.read_text())
    existing.append({
        "ts": int(time.time()),
        "summary": {k: v for k, v in agg.items() if k != "results"},
        "raw": agg["results"],
    })
    RECEIPTS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS.keys()) + ["all"], default="haiku")
    ap.add_argument("--all", action="store_true",
                    help="iterate all 10 models with shared budget")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--budget-cap", type=float, default=DEFAULT_BUDGET_CAP_USD)
    ap.add_argument("--reset-budget", action="store_true",
                    help="reset cumulative spend tracker before run")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true",
                    help="append summary to cache_lab_receipts.json")
    ap.add_argument("--system-tokens", type=int, default=0,
                    help="override stable system prompt size (target tokens). "
                         "0 means default ~5772-token prompt")
    ap.add_argument("--provider-pin", type=str, default=None,
                    help="override force_provider for this run (empty string clears it)")
    args = ap.parse_args()

    budget = BudgetTracker(cap_usd=args.budget_cap)
    if args.reset_budget:
        budget.reset()

    targets = list(MODELS.keys()) if (args.all or args.model == "all") else [args.model]
    sys_prompt = (build_system_prompt(args.system_tokens)
                  if args.system_tokens > 0 else STABLE_SYSTEM_PROMPT)

    print(f"Cache lab — models={targets}, runs={args.runs}, "
          f"budget_cap=${args.budget_cap}, current=${budget.total():.4f}",
          file=sys.stderr)
    print(f"System prompt: ~{len(sys_prompt) // 4} tokens "
          f"({'custom' if args.system_tokens else 'default'})", file=sys.stderr)
    if args.provider_pin is not None:
        print(f"Provider pin override: {args.provider_pin or '(cleared)'}",
              file=sys.stderr)
    print(file=sys.stderr)

    aggregates: list[dict] = []
    for key in targets:
        if not budget.can_spend(0.10):
            print(f"BUDGET CAP — skipping {key}, total=${budget.total():.4f}",
                  file=sys.stderr)
            break
        print(f"\n=== {key} ({MODELS[key]['slug']}) ===", file=sys.stderr)
        agg = run_lab(key, args.runs, budget, sleep_s=args.sleep,
                      system_prompt=sys_prompt,
                      provider_pin=args.provider_pin)
        aggregates.append(agg)
        if args.save:
            _save_summary(agg)
            print(f"Saved → {RECEIPTS_PATH}", file=sys.stderr)
        if agg["aborted"] and len(targets) > 1:
            print("Run aborted — stopping multi-model loop.", file=sys.stderr)
            break

    if args.json:
        print(json.dumps(aggregates, ensure_ascii=False, indent=2))
    else:
        print()
        print("=== Final ===")
        print(f"  Total spend:          ${budget.total():.4f} of "
              f"${args.budget_cap:.2f} cap")
        print(f"  Models completed:     {len(aggregates)}")
        for agg in aggregates:
            print(f"  {agg['model_key']:14s} "
                  f"runs={agg['runs_succeeded']:>2}/{agg['runs_requested']:<2}  "
                  f"hit={agg['cache_hit_rate_pct']:>5.1f}%  "
                  f"save={agg['total_savings_pct']:>5.1f}%  "
                  f"act=${agg['total_actual_cost_usd']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
