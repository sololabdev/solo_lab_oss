# opus-4-7-context-test

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-7%20passing-green)
![Status](https://img.shields.io/badge/status-active-green)

A reproducible harness for testing where Anthropic Claude Opus 4.7's
effective context length actually ends — on **your** codebase, not a
synthetic needle-in-haystack benchmark.

Backs the long-form post **["I expected Opus 4.7 to fall off a cliff at
1M tokens. It didn't."](https://solo-lab.dev/posts/opus-4-7-context-cliff)**

## Reproduce in 60 seconds

```bash
git clone https://github.com/sololabdev/solo_lab_oss
cd solo_lab_oss/opus-4-7-context-test
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-v1-...
cd src && python context_loader.py --offline   # build fixture, ~10s
python benchmark_opus_47.py --backend openrouter \
    --sizes 150000 --filter-category needle --limit 1   # 1 call, ~$0.05
```

First successful run takes ~60 seconds and produces a single
needle-retrieval answer. Full benchmark (150 calls × 5 sizes) is ~$25
on OpenRouter.

## What you get out

Each call appends one JSON line to `runs/<stamp>/results.jsonl`:

```json
{
  "context_size": 150000,
  "question_id": "n01",
  "category": "needle",
  "prompt": "What port does the gateway bind to in production?",
  "canonical_answer": "18789",
  "answer": "The gateway binds to port 18789 in production (see config/server.py:42).",
  "input_tokens": 149832,
  "output_tokens": 24,
  "cache_read_input_tokens": 149832,
  "cost_usd": 0.0021,
  "elapsed_s": 3.4,
  "auto_score": "correct"
}
```

A `summary.json` per run rolls up totals + needle auto-score counts.
`report_run.py` turns a scored run into the HN-ready markdown table.

## What this measures

- 30 hand-built questions in 3 categories: needle (single-fact lookup),
  multi-hop (trace data flow across modules), refactor (synthesis: "if
  we deprecate X, what breaks?").
- Each question asked at up to 5 context loads: 150K, 500K, 700K, 900K, 1M
  input tokens. The bundled fixture ships configurable targets via
  `--targets`.
- 90–150 model calls per full run. Cost ≈ $5–10 with Anthropic prompt
  caching, or ≈ $25–30 without (e.g. via OpenRouter). The Solo Lab
  reference run was $0 — routed through Claude Code subagents.
- Auto-scores `needle` answers via canonical-keyword match. Scoring of
  `multihop` and `refactor` is manual — by design, no LLM-as-judge.

## What this measured for Solo Lab (one run, one codebase)

> Going in I expected the standard "1M is marketing, ~500K is the real
> ceiling" curve. **The data didn't cooperate.** Across 30 Q × 5 sizes:
> needle retrieval flat at 100%, multi-hop 90–95%, refactor (manual
> review) 95% — at every size including 1M. No cliff.
> Full numbers in the linked post.

Your numbers will differ. The harness ships a small bundled fixture so
the first run produces meaningful output without any setup. Substitute
your own files (and your own questions) for a real test.

## Full run, scoring, and report

Once the 60-second smoke test works, the rest of the harness is three
commands. Use `ANTHROPIC_API_KEY=sk-ant-...` instead of OpenRouter to
get prompt-caching discounts (~$8 vs ~$25 for a full run).

```bash
# Full run (~25–40 min wall time, ~$25 on OpenRouter / ~$8 on Anthropic-direct)
python benchmark_opus_47.py

# Score: auto for needle, interactive for multi-hop / refactor
python score_run.py <run_id>
python score_run.py <run_id> --auto-only   # fast preview, needle only

# HN-ready summary table
python report_run.py <run_id>
```

## Running on your OWN codebase

The bundled fixture gives the harness something concrete to grind on
out-of-the-box, but the questions are written against the fixture, not
your code. To test your codebase you need two things:

### 1. Point the loader at your code

```bash
python context_loader.py --corpus-dir /path/to/your/repo
```

The loader pulls all `.py` / `.md` / `.json` files recursively in
sorted order until each token target is reached. If your corpus is
smaller than the target, deterministic filler is appended.

### 2. Write your own `questions.json`

Format documented in `fixtures/sample_questions.json`. Each question:

```json
{
  "id": "n01",
  "category": "needle",
  "prompt": "Exact prompt sent to the model",
  "canonical_answer": "What you'd accept as correct",
  "scorer_keywords": ["must_appear_substring"],
  "forbidden_keywords": ["if_present_marks_as_wrong"]
}
```

Then:

```bash
python benchmark_opus_47.py --questions /path/to/your/questions.json
```

10 questions per category (needle / multihop / refactor) takes about
30 minutes of writing time and is what the post is built on. Smaller
runs (e.g. 5 per category) work fine for kicking the tires.

## Files in this project

| File | What it does |
|---|---|
| `src/context_loader.py` | Builds context loads from a corpus directory. `--offline` for char/4 estimate (free), online for accurate `count_tokens`. |
| `src/benchmark_opus_47.py` | The runner. Sends 30 × 3 = 90 calls. Logs to `runs/<stamp>/results.jsonl`. Uses prompt caching on Anthropic-direct. |
| `src/llm_client.py` | Two backends: `anthropic` (with caching, cheaper) and `openrouter` (fallback). |
| `src/score_run.py` | Auto-scores needle; interactive grader for multi-hop and refactor. Writes `scored.jsonl`. |
| `src/report_run.py` | Reads `scored.jsonl`, emits `report.md` with summary table + cliff threshold + hallucination examples. |
| `fixtures/sample_repo/` | 4-file hypothetical Python codebase used as the default corpus. |
| `fixtures/sample_questions.json` | 9 questions (3 needle + 3 multi-hop + 3 refactor) about the sample repo. |

## Caveats (what this is NOT)

- **n=90, scored by one builder.** Not a SOTA benchmark. The point is
  reproducibility on your own working set.
- **Single-language.** Models do better on Python than (say) Erlang.
  Your codebase aesthetic matters.
- **No zero-context baseline.** This doesn't compare against the model's
  parametric knowledge alone. Trust the *shape* of degradation more
  than the absolute magnitude.
- **Prompt position effects** ([Lost in the
  Middle](https://arxiv.org/abs/2307.03172)) are real and likely affect
  where the cliff sits.
- **Anthropic may patch this.** Context utilization curves shift with
  each model update.

## License

MIT. If you run this on your own codebase and get different numbers,
open an issue with the comparison — that's the whole point.
