# opus-4-7-context-test

A reproducible harness for testing where Anthropic Claude Opus 4.7's
effective context length actually ends — on **your** codebase, not a
synthetic needle-in-haystack benchmark.

Backs the long-form post **["I gave Opus 4.7 a 700K-token codebase. Here's
where it broke."](https://solo-lab.dev/posts/opus-4-7-context-cliff)**

## What this measures

- 30 hand-built questions in 3 categories: needle (single-fact lookup),
  multi-hop (trace data flow across modules), refactor (synthesis: "if
  we deprecate X, what breaks?").
- Each question asked at 3 context loads: 150K, 500K, 700K input tokens.
- 90 model calls total. Cost ≈ $5–10 with Anthropic prompt caching, or
  ≈ $25–30 without (e.g. via OpenRouter).
- Auto-scores `needle` answers via canonical-keyword match. Scoring of
  `multihop` and `refactor` is manual — by design, no LLM-as-judge.

## What this finds (hypothesis, before you run it)

> The single-builder hypothesis I'm testing: **1M is a marketing number,
> ~500K is the practical ceiling for code-grade reasoning, and dumping
> the full context past that line is a 2–7× paid downgrade.**

Real numbers depend on your codebase. The harness ships a small bundled
fixture so the first run produces meaningful output without any setup.
Substitute your own files (and your own questions) for a real test.

## Quick start (uses bundled fixture)

```bash
git clone https://github.com/sololabdev/solo_lab_oss
cd solo_lab_oss/opus-4-7-context-test

pip install -r requirements.txt

# Either:
export ANTHROPIC_API_KEY=sk-ant-...        # direct, with prompt caching
# or:
export OPENROUTER_API_KEY=sk-or-v1-...     # fallback, no caching discount

# 1. Build context loads from the bundled fixture (~10 s, free)
cd src
python context_loader.py --offline

# 2. Validate setup (no API calls)
python benchmark_opus_47.py --dry-run

# 3. Smoke-test on 1 needle question at 150K
python benchmark_opus_47.py --backend openrouter \
                            --sizes 150000 \
                            --filter-category needle \
                            --limit 1

# 4. Full run (~25–40 min wall time, ~$25 on OpenRouter / ~$8 on Anthropic-direct)
python benchmark_opus_47.py

# 5. Score the run
python score_run.py <run_id>             # interactive (multi-hop / refactor manual)
python score_run.py <run_id> --auto-only # auto-score needle only (fast preview)

# 6. Generate the HN-ready table
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
