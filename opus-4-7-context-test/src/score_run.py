"""
Scoring helper for an Opus 4.7 benchmark run.

Reads benchmark/runs/<run_id>/results.jsonl and:
- Confirms auto-scores for `needle` questions.
- For multi-hop and refactor questions, prints prompt + canonical answer + model
  answer and asks for a 1-letter manual grade: c=correct, p=partial, w=wrong,
  h=hallucinated. Saves the verdict back to scored.jsonl.

Run with:
  python score_run.py <run_id>      # interactive
  python score_run.py <run_id> --auto-only  # only auto-score needle, skip prompt

After scoring is done, run:
  python report_run.py <run_id>     # produces the HN-ready markdown table
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", help="e.g. 2026-04-28_120000")
    ap.add_argument("--auto-only", action="store_true",
                    help="Skip interactive prompts; mark non-needle as 'unscored'")
    args = ap.parse_args()

    run_dir = RUNS_DIR / args.run_id
    if not run_dir.exists():
        sys.exit(f"Run dir not found: {run_dir}")
    results_path = run_dir / "results.jsonl"
    scored_path = run_dir / "scored.jsonl"

    # Robust JSONL parse — skip malformed lines (e.g. truncated final line
    # from a mid-call crash) instead of aborting the entire scoring session.
    records = []
    skipped = 0
    for i, line in enumerate(results_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            skipped += 1
            print(f"  WARN: skip malformed line {i}: {e}", file=sys.stderr)
    print(f"Loaded {len(records)} records from {results_path}"
          + (f" (skipped {skipped} malformed)" if skipped else ""))

    scored: list[dict] = []
    for r in records:
        if "error" in r:
            r["score"] = "error"
            scored.append(r)
            continue

        if r["category"] == "needle":
            r["score"] = r.get("auto_score") or "wrong"
            scored.append(r)
            continue

        if args.auto_only:
            r["score"] = "unscored"
            scored.append(r)
            continue

        # Manual grade
        print("=" * 80)
        print(f"[{r['category']}] {r['question_id']} @ {r['context_size']:,} ctx")
        print(f"PROMPT:    {r['prompt']}")
        print(f"CANONICAL: {r['canonical_answer']}")
        print(f"MODEL:     {r['answer'][:1500]}")
        while True:
            grade = input("grade (c/p/w/h, or s=skip): ").strip().lower()
            if grade in ("c", "p", "w", "h", "s"):
                break
        if grade == "s":
            r["score"] = "unscored"
        else:
            r["score"] = {"c": "correct", "p": "partial",
                          "w": "wrong", "h": "hallucinated"}[grade]
        scored.append(r)

    with scored_path.open("w") as f:
        for r in scored:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nSaved {len(scored)} scored records to {scored_path}")


if __name__ == "__main__":
    main()
