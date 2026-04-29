"""
Generate HN-ready markdown table from a scored benchmark run.

Reads benchmark/runs/<run_id>/scored.jsonl and emits report.md with:
- The summary table (context size × category × correct/total + avg cost/query)
- A section listing hallucination examples (model answers that confabulated)
- The headline cliff threshold (where multi-hop drops below 80%)

Run:
  python report_run.py <run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    args = ap.parse_args()

    run_dir = RUNS_DIR / args.run_id
    scored = run_dir / "scored.jsonl"
    if not scored.exists():
        sys.exit(f"Run scoring first: python score_run.py {args.run_id}")

    records = [json.loads(line) for line in scored.read_text().splitlines() if line.strip()]

    # Aggregate: (size, category) -> {correct, partial, wrong, hallucinated, error, total, cost_sum, n_cost}
    agg: dict[tuple[int, str], dict] = defaultdict(
        lambda: {"correct": 0, "partial": 0, "wrong": 0, "hallucinated": 0,
                 "error": 0, "unscored": 0, "total": 0, "cost_sum": 0.0,
                 "n_cost": 0, "elapsed_sum": 0.0}
    )
    halluc_examples: list[dict] = []
    for r in records:
        key = (r["context_size"], r["category"])
        bucket = agg[key]
        bucket["total"] += 1
        s = r.get("score", "unscored")
        bucket[s] = bucket.get(s, 0) + 1
        if "cost_usd" in r:
            bucket["cost_sum"] += r["cost_usd"]
            bucket["n_cost"] += 1
            bucket["elapsed_sum"] += r.get("elapsed_s", 0)
        if s == "hallucinated":
            halluc_examples.append(r)

    # Per-size aggregates for cost
    per_size_cost: dict[int, list[float]] = defaultdict(list)
    for r in records:
        if "cost_usd" in r:
            per_size_cost[r["context_size"]].append(r["cost_usd"])

    out = ["# Opus 4.7 1M-context cliff benchmark — run " + args.run_id, ""]

    # Sizes in canonical order
    sizes = sorted({r["context_size"] for r in records if "context_size" in r})
    cats = ["needle", "multihop", "refactor"]

    # Summary table (matches HN post structure)
    out.append("## Summary")
    out.append("")
    out.append("| Context | Needle | Multi-hop | Refactor | Avg cost/query |")
    out.append("|---|---|---|---|---|")
    for sz in sizes:
        row = [f"{sz//1000}K"]
        for cat in cats:
            b = agg.get((sz, cat))
            if not b:
                row.append("—")
            else:
                # "correct + partial / total" formatted as score
                ok = b.get("correct", 0)
                tot = b["total"] - b.get("error", 0)
                row.append(f"{ok}/{tot}")
        costs = per_size_cost.get(sz, [])
        avg = (sum(costs) / len(costs)) if costs else 0
        row.append(f"${avg:.2f}")
        out.append("| " + " | ".join(row) + " |")
    out.append("")

    # Per-category breakdown with partial/wrong/halluc detail
    out.append("## Detail")
    out.append("")
    for sz in sizes:
        out.append(f"### Context: {sz:,} tokens")
        out.append("")
        out.append("| Category | Correct | Partial | Wrong | Hallucinated | Errors |")
        out.append("|---|---|---|---|---|---|")
        for cat in cats:
            b = agg.get((sz, cat), {})
            out.append(
                f"| {cat} | {b.get('correct',0)} | {b.get('partial',0)} | "
                f"{b.get('wrong',0)} | {b.get('hallucinated',0)} | "
                f"{b.get('error',0)} |"
            )
        out.append("")

    # Cliff position
    out.append("## Where the cliff sits")
    out.append("")
    cliff_lines = []
    for cat in cats:
        for sz in sizes:
            b = agg.get((sz, cat), {})
            tot = max(b.get("total", 0) - b.get("error", 0), 1)
            ok_pct = 100.0 * b.get("correct", 0) / tot
            if ok_pct < 80:
                cliff_lines.append(
                    f"- **{cat}** drops below 80% correct at **{sz:,} tokens** "
                    f"({b.get('correct',0)}/{tot} = {ok_pct:.0f}%)."
                )
                break
    if not cliff_lines:
        cliff_lines.append("- No category dropped below 80% within tested sizes.")
    out += cliff_lines
    out.append("")

    # Hallucination examples (show first 3)
    out.append("## Hallucination examples")
    out.append("")
    if halluc_examples:
        for r in halluc_examples[:3]:
            out.append(f"### {r['question_id']} @ {r['context_size']:,} tokens "
                       f"({r['category']})")
            out.append("")
            out.append(f"**Prompt:** {r['prompt']}")
            out.append("")
            out.append(f"**Canonical:** {r['canonical_answer']}")
            out.append("")
            out.append(f"**Model:** {r['answer'][:800]}")
            out.append("")
    else:
        out.append("None recorded in this run.")
        out.append("")

    # Total spend
    total_cost = sum(r.get("cost_usd", 0) for r in records)
    total_calls = sum(1 for r in records if "cost_usd" in r)
    out.append("## Run totals")
    out.append("")
    out.append(f"- Calls completed: **{total_calls}**")
    out.append(f"- Total spend: **${total_cost:.2f}**")
    out.append(f"- Errors / retries failed: "
               f"**{sum(1 for r in records if 'error' in r)}**")
    out.append("")

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(out))
    print(f"Wrote {report_path}")
    print()
    print("\n".join(out[:30]))  # head preview


if __name__ == "__main__":
    main()
