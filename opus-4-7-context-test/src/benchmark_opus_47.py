"""
Opus 4.7 1M-context cliff benchmark — Solo Lab.

Runs 30 questions × 3 context sizes (150K, 500K, 700K) = 90 model calls,
logs full responses + per-call cost + per-call latency to a JSONL file.

Auto-scores `needle` category questions (deterministic keyword match).
Saves `multihop` and `refactor` results with their canonical answers
attached for manual scoring (the HN post commits to manual scoring).

Requires:
  Either ANTHROPIC_API_KEY (with balance) or the OpenRouter key file at
  ~/.openclaw/credentials/openrouter-api-key.txt
  benchmark/cache/load_{150000,500000,700000}.txt   (build via context_loader.py)

Usage:
  python benchmark_opus_47.py                       # full run, all 3 sizes
  python benchmark_opus_47.py --sizes 150000        # subset for dev
  python benchmark_opus_47.py --dry-run             # validate setup, do not call API
  python benchmark_opus_47.py --backend openrouter  # use OpenRouter (no cache discount)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CACHE_DIR = ROOT / "cache"
RUNS_DIR = ROOT / "runs"
DEFAULT_QUESTIONS_PATH = PROJECT_ROOT / "fixtures" / "sample_questions.json"

MODEL = "claude-opus-4-7"
INPUT_USD_PER_M = 15.0
OUTPUT_USD_PER_M = 75.0
MAX_TOKENS_OUT = 600  # answers should be short; refactors can run a bit longer
SLEEP_BETWEEN_CALLS = 2.0  # rate-limit safety
RETRY_SLEEP = [10, 30, 90]  # exponential-ish backoff on rate-limit / overload


def load_questions(questions_path: Path) -> list[dict]:
    data = json.loads(questions_path.read_text())
    return data["questions"]


def load_context(size: int) -> str:
    p = CACHE_DIR / f"load_{size}.txt"
    if not p.exists():
        sys.exit(
            f"Missing context cache {p}. Run `python context_loader.py` first."
        )
    return p.read_text()


def cost_usd(usage) -> float:
    inp = (usage.input_tokens or 0) / 1_000_000.0 * INPUT_USD_PER_M
    out = (usage.output_tokens or 0) / 1_000_000.0 * OUTPUT_USD_PER_M
    return round(inp + out, 4)


def call_with_retry(backend, system_blocks, q_prompt):
    last_err = None
    for attempt in range(len(RETRY_SLEEP) + 1):
        try:
            return backend.call(MODEL, system_blocks, q_prompt, MAX_TOKENS_OUT)
        except Exception as e:  # rate-limit, overload, transient 5xx
            last_err = e
            msg = str(e)[:300]
            print(f"   ! attempt {attempt+1} failed: {type(e).__name__}: {msg}",
                  file=sys.stderr)
            if attempt < len(RETRY_SLEEP):
                time.sleep(RETRY_SLEEP[attempt])
            else:
                raise
    raise last_err  # unreachable


def auto_score_needle(answer_text: str, q: dict) -> str:
    """Returns 'correct' / 'partial' / 'wrong' for needle questions.

    For short numeric keywords (≤3 chars), require a word-boundary match to
    avoid false positives where the model mentions the digit incidentally
    (e.g. "30 FPS is common" matching keyword '30'). Longer keywords use
    plain substring match — they're already specific enough.
    """
    import re
    text_lower = answer_text.lower()
    needed = len(q["scorer_keywords"])
    hits = 0
    for kw in q["scorer_keywords"]:
        kw_l = kw.lower()
        if len(kw_l) <= 3 and kw_l.replace(".", "").isdigit():
            # Numeric tokens — require word boundary to avoid noise matches.
            if re.search(r"(?<![\w.])" + re.escape(kw_l) + r"(?![\w])", text_lower):
                hits += 1
        elif kw_l in text_lower:
            hits += 1
    forbidden_hits = sum(
        1 for kw in q.get("forbidden_keywords", []) if kw.lower() in text_lower
    )
    if forbidden_hits > 0:
        return "wrong"  # forbidden = confabulation tell
    if hits == needed:
        return "correct"
    if hits > 0:
        return "partial"
    return "wrong"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+",
                    default=[150_000, 500_000, 700_000])
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate setup; do not call API")
    ap.add_argument("--filter-category", choices=["needle", "multihop", "refactor"])
    ap.add_argument("--limit", type=int, default=0,
                    help="Run only first N questions per size (for dev)")
    ap.add_argument("--backend", choices=["anthropic", "openrouter"],
                    default=os.environ.get("LLM_BACKEND", "anthropic"),
                    help="anthropic = direct SDK with prompt caching (cheaper). "
                         "openrouter = fallback when Anthropic balance is dry.")
    ap.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH,
                    help=f"Path to questions.json. Default: "
                         f"{DEFAULT_QUESTIONS_PATH.relative_to(PROJECT_ROOT)} "
                         "(bundled fixture with 9 questions on the sample repo). "
                         "Override with your own for your codebase.")
    args = ap.parse_args()

    if not args.questions.exists():
        sys.exit(f"questions file not found: {args.questions}")
    questions = load_questions(args.questions)
    if args.filter_category:
        questions = [q for q in questions if q["category"] == args.filter_category]
    if args.limit:
        questions = questions[: args.limit]
    print(f"Questions: {len(questions)} ({', '.join(args.filter_category and [args.filter_category] or ['all categories'])})")

    # Pre-load contexts (and verify they exist)
    contexts = {sz: load_context(sz) for sz in args.sizes}
    print("Context loads ready:",
          {sz: f"{len(t)} chars" for sz, t in contexts.items()})

    if args.dry_run:
        print("DRY-RUN OK. Exiting before API calls.")
        return

    # Backend selection (anthropic | openrouter)
    from llm_client import get_backend
    backend = get_backend(args.backend)
    print(f"Backend: {backend.name}"
          + ("  (no cache discount on OpenRouter — full input billed each call)"
             if backend.name == "openrouter" else ""))

    # Output dir for this run
    stamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    out_dir = RUNS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    print(f"Run output -> {results_path}")

    total_cost = 0.0
    total_calls = 0
    auto_correct = 0
    auto_partial = 0
    auto_wrong = 0

    with results_path.open("w") as fout:
        for size in args.sizes:
            ctx_text = contexts[size]
            # Use cache_control on the context block so repeated questions at the
            # same size hit the prompt cache (huge cost saving across 30 Qs).
            system_blocks = [
                {
                    "type": "text",
                    "text": (
                        "You are a careful code reasoning assistant. The context "
                        "below contains the user's full repository plus reference "
                        "material. Answer questions strictly from that context. "
                        "If the context does not contain enough information to "
                        "answer with certainty, say so explicitly. Do not invent "
                        "files, functions, or values."
                    ),
                },
                {
                    "type": "text",
                    "text": "<repository_context>\n" + ctx_text + "\n</repository_context>",
                    "cache_control": {"type": "ephemeral"},
                },
            ]
            print(f"\n=== context size: {size:,} tokens ===")
            for q in questions:
                print(f"  [{q['category']:8s}] {q['id']} ...", end=" ", flush=True)
                try:
                    resp = call_with_retry(backend, system_blocks, q["prompt"])
                except Exception as e:
                    record = {
                        "ts": time.time(),
                        "context_size": size,
                        "question_id": q["id"],
                        "category": q["category"],
                        "error": f"{type(e).__name__}: {str(e)[:300]}",
                    }
                    fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                    fout.flush()
                    print("ERR")
                    continue

                answer_text = resp.text
                cost = resp.cost_usd or 0.0
                total_cost += cost
                total_calls += 1

                auto_score = None
                if q["category"] == "needle":
                    auto_score = auto_score_needle(answer_text, q)
                    if auto_score == "correct":
                        auto_correct += 1
                    elif auto_score == "partial":
                        auto_partial += 1
                    else:
                        auto_wrong += 1

                record = {
                    "ts": time.time(),
                    "context_size": size,
                    "question_id": q["id"],
                    "category": q["category"],
                    "prompt": q["prompt"],
                    "canonical_answer": q["canonical_answer"],
                    "answer": answer_text,
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "cache_creation_input_tokens": resp.cache_creation_input_tokens,
                    "cache_read_input_tokens": resp.cache_read_input_tokens,
                    "cost_usd": cost,
                    "elapsed_s": round(resp.elapsed_s, 2),
                    "backend": resp.backend,
                    "auto_score": auto_score,
                }
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                fout.flush()
                tag = auto_score or "—"
                print(f"OK  {tag:7s}  ${cost:.4f}  {resp.elapsed_s:.1f}s")
                time.sleep(SLEEP_BETWEEN_CALLS)

    summary = {
        "run": stamp,
        "model": MODEL,
        "questions": len(questions),
        "context_sizes": args.sizes,
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 4),
        "auto_score_needle": {
            "correct": auto_correct,
            "partial": auto_partial,
            "wrong": auto_wrong,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nNext: review results in {results_path}")
    print("Run scoring helper:  python score_run.py", out_dir.name)


if __name__ == "__main__":
    main()
