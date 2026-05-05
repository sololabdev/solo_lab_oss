#!/usr/bin/env python3
"""Generate cache_lab_summary.md — comparison table from cache_lab_receipts.json.

Reads receipts; groups by model_key; emits a markdown table + per-call observations.
Run: python3 cache_lab_summary.py > cache_lab_summary.md
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
RECEIPTS_PATH = ROOT / "cache_lab_receipts.json"
CALLS_LOG_PATH = ROOT / "cache_lab_calls.jsonl"
BUDGET_PATH = ROOT / "cache_lab_budget.json"


def load_receipts() -> list[dict]:
    if not RECEIPTS_PATH.exists():
        return []
    return json.loads(RECEIPTS_PATH.read_text())


def load_calls() -> list[dict]:
    if not CALLS_LOG_PATH.exists():
        return []
    rows = []
    for line in CALLS_LOG_PATH.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def latest_per_model(receipts: list[dict]) -> dict[str, dict]:
    """Keep only the most recent default-prefix-size summary per model."""
    out: dict[str, dict] = {}
    for entry in receipts:
        s = entry.get("summary", {})
        key = s.get("model_key") or s.get("model")
        if not key:
            continue
        # Skip prefix-scaling and pin-override variants — they get their own sections
        if s.get("system_prompt_token_estimate", 5772) > 7000:
            continue
        if s.get("provider_pin_override"):
            continue
        if key not in out or entry["ts"] > out[key]["ts"]:
            out[key] = entry
    return out


def haiku_scaling_runs(receipts: list[dict]) -> list[dict]:
    """All haiku runs across prefix sizes (5K / 30K / 100K)."""
    out = []
    for entry in receipts:
        s = entry.get("summary", {})
        if (s.get("model_key") == "haiku"
                and s.get("runs_succeeded", 0) >= 5):
            out.append(entry)
    out.sort(key=lambda e: e["summary"].get("system_prompt_token_estimate", 0))
    return out


def pin_override_runs(receipts: list[dict]) -> list[dict]:
    """All runs where provider_pin_override was used."""
    return [e for e in receipts
            if e.get("summary", {}).get("provider_pin_override")]


def fmt_pct(v: float) -> str:
    return f"{v:>5.1f}%"


def main() -> int:
    receipts = load_receipts()
    if not receipts:
        print("No receipts found.", file=sys.stderr)
        return 1

    by_model = latest_per_model(receipts)
    haiku_scaling = haiku_scaling_runs(receipts)
    pin_overrides = pin_override_runs(receipts)
    calls = load_calls()
    budget = json.loads(BUDGET_PATH.read_text()) if BUDGET_PATH.exists() else {}

    total_spend = budget.get("total_spent_usd", sum(
        e["summary"].get("total_actual_cost_usd", 0) for e in by_model.values()
    ))
    total_calls = budget.get("calls", sum(
        e["summary"].get("runs_succeeded", 0) for e in by_model.values()
    ))

    # Header
    order = ["haiku", "sonnet", "opus", "gpt4o-mini", "gpt4o", "gpt55",
             "gemini-flash", "gemini-pro", "deepseek", "llama"]
    models_in_order = sum(1 for k in order if k in by_model)

    print("# Cache Lab — Multi-Model Benchmark Summary")
    print()
    print(f"_Generated: {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}_")
    print()
    print(f"- **Models tested:** {models_in_order}")
    print(f"- **Total calls:** {total_calls}")
    print(f"- **Total spend:** ${total_spend:.4f}")
    print(f"- **Default stable prefix:** ~5,772 tokens (BRAND.md proxy); scaling rows below at 30K and 100K")
    print(f"- **User messages:** 10 base, cycled per run")
    print()

    # Per-model comparison table
    print("## Comparison table")
    print()
    print("| Model | Cache type | Provider | Runs | Hit rate | Total savings | Actual $ | No-cache $ |")
    print("|---|---|---|---|---|---|---|---|")

    for key in order:
        if key not in by_model:
            print(f"| `{key}` | — | — | — | — | — | — | not run |")
            continue
        s = by_model[key]["summary"]
        # Routed provider may differ from forced — pull from raw rows
        raw = by_model[key]["raw"]
        providers = {r.get("provider") for r in raw if "provider" in r and "error" not in r}
        prov_str = ", ".join(sorted(p for p in providers if p)) or "?"
        print(
            f"| `{s['model']}` "
            f"| {s.get('cache_type', '?')} "
            f"| {prov_str} "
            f"| {s['runs_succeeded']}/{s['runs_requested']} "
            f"| {fmt_pct(s['cache_hit_rate_pct'])} "
            f"| {fmt_pct(s['total_savings_pct'])} "
            f"| ${s['total_actual_cost_usd']:.4f} "
            f"| ${s['total_no_cache_hypothetical_usd']:.4f} |"
        )

    # Notable findings
    print()
    print("## Notable observations")
    print()
    for key in order:
        if key not in by_model:
            continue
        s = by_model[key]["summary"]
        raw = [r for r in by_model[key]["raw"] if "error" not in r]
        if not raw:
            print(f"- **{key}**: 0 successful calls.")
            continue

        first_call_cw = raw[0]["cache_creation_input_tokens"]
        first_call_cr = raw[0]["cache_read_input_tokens"]
        cache_hits = sum(1 for r in raw if r["cache_read_input_tokens"] > 0)
        cache_misses_after_first = sum(
            1 for r in raw[1:] if r["cache_read_input_tokens"] == 0
        )
        avg_ms = sum(r["elapsed_ms"] for r in raw) // len(raw)

        notes = []
        if first_call_cw > 0:
            notes.append(f"first call wrote {first_call_cw:,} tokens to cache")
        if first_call_cr > 0:
            notes.append("first call hit cache (warm prefix from prior session)")
        if cache_misses_after_first > 0:
            notes.append(f"{cache_misses_after_first} mid-run cache misses (TTL eviction)")
        if cache_hits == len(raw):
            notes.append("100% cache hit across all calls")
        elif cache_hits == 0:
            notes.append("zero cache hits — provider doesn't expose them or didn't cache")

        notes.append(f"avg latency {avg_ms}ms")

        slug = s["model"]
        print(f"- **`{slug}`** — " + "; ".join(notes) + ".")

    # Prefix-size scaling on Haiku
    if haiku_scaling:
        print()
        print("## Prefix-size scaling — `claude-haiku-4.5`")
        print()
        print("How does cache savings scale with stable prefix size? "
              "Same model, same provider pin, varying system prompt token count.")
        print()
        print("| Prefix tokens | Runs | Hit rate | Real savings | Actual $/call | "
              "No-cache $/call | Latency |")
        print("|---|---|---|---|---|---|---|")
        for entry in haiku_scaling:
            s = entry["summary"]
            raw = [r for r in entry["raw"] if "error" not in r]
            if not raw:
                continue
            n = max(1, len(raw))
            avg_ms = sum(r["elapsed_ms"] for r in raw) // n
            avg_act = s["total_actual_cost_usd"] / n
            avg_no = s["total_no_cache_hypothetical_usd"] / n
            print(
                f"| ~{s['system_prompt_token_estimate']:>6,} "
                f"| {s['runs_succeeded']}/{s['runs_requested']} "
                f"| {fmt_pct(s['cache_hit_rate_pct'])} "
                f"| {fmt_pct(s['total_savings_pct'])} "
                f"| ${avg_act:.5f} "
                f"| ${avg_no:.5f} "
                f"| {avg_ms}ms |"
            )

    # Pin-override comparison runs
    if pin_overrides:
        print()
        print("## Pin-override sanity tests")
        print()
        print("Re-runs with `--provider-pin <X>` to test the auto-shard hypothesis.")
        print()
        print("| Model | Pin | Hit rate | Savings | Actual $ | Notes |")
        print("|---|---|---|---|---|---|")
        for entry in pin_overrides:
            s = entry["summary"]
            raw = [r for r in entry["raw"] if "error" not in r]
            providers = sorted({r.get("provider") for r in raw if "provider" in r})
            prov_str = ", ".join(p for p in providers if p) or "?"
            misses = sum(1 for r in raw if r.get("cache_read_input_tokens", 0) == 0)
            print(
                f"| `{s['model']}` "
                f"| {s['provider_pin_override']} (got: {prov_str}) "
                f"| {fmt_pct(s['cache_hit_rate_pct'])} "
                f"| {fmt_pct(s['total_savings_pct'])} "
                f"| ${s['total_actual_cost_usd']:.4f} "
                f"| {misses}/{len(raw)} misses |"
            )

    # Open question receipts
    print()
    print("## Open questions answered by this dataset")
    print()
    print("1. **Same vs different user message** — answered by raw call log")
    print("   (`cache_lab_calls.jsonl`); user_msg_preview lets you group by hash.")
    print()
    print("2. **Hit rate by prefix size** — partially answered. All runs use a")
    print("   ~5.8K-token prefix; rerun with `--system-tokens 30k` for scaling.")
    print()
    print("3. **OpenAI implicit caching consistency** — see gpt-4o-mini / gpt-4o /")
    print("   gpt-5.5 rows above. Cache fields populated only when prefix ≥1024")
    print("   tokens AND the same prefix has been seen recently.")
    print()
    print("4. **Gemini implicit cache** — see gemini-flash / gemini-pro. Their")
    print("   `prompt_tokens_details.cached_tokens` fires only at certain sizes.")
    print()
    print("5. **OpenRouter cross-region routing** — provider column in the table")
    print("   above shows where each call landed. Anthropic + Google + DeepSeek")
    print("   were force-pinned via `provider.only`; others were auto-routed.")
    print()

    print("## Receipts")
    print()
    print("- Per-call rows: `cache_lab_calls.jsonl` (300+ rows)")
    print("- Per-model summaries: `cache_lab_receipts.json`")
    print("- Cumulative budget: `cache_lab_budget.json`")

    return 0


if __name__ == "__main__":
    sys.exit(main())
