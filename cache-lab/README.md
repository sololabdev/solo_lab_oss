# cache-lab

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-10%20passing-green)
![Stdlib only](https://img.shields.io/badge/deps-stdlib%20only-blue)

Reproducible benchmark for **real prompt-cache hit rate and billed
savings** across 10 production LLMs via OpenRouter — Claude Haiku 4.5,
Sonnet 4.6, Opus 4.7, GPT-4o-mini, GPT-4o, GPT-5.5, Gemini 2.5 Flash,
Gemini 2.5 Pro, DeepSeek-Chat-v3.1, Llama-3.3-70b.

The marketing claim is "90% off cached input." This harness measures
**what each provider's `usage.cost` field actually says** after 30
identical-prefix calls. No SDK, no provider abstraction — bare
`urllib.request` against OpenRouter's chat-completions endpoint.

Backs the long-form post _"Real cached-token discounts across 10 LLMs —
389 calls, $1.79, receipts inside."_ (link tk).

## Reproduce in 60 seconds

```bash
git clone https://github.com/sololabdev/solo_lab_oss
cd solo_lab_oss/cache-lab
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-v1-...
cd src && python cache_lab.py --model haiku --runs 10 --save
```

First run: ~30 sec, ~$0.02. Output goes to `cache_lab_receipts.json` +
`cache_lab_calls.jsonl` next to the script.

Full multi-model sweep (10 models × 30 calls):

```bash
python cache_lab.py --all --runs 30 --save --reset-budget
```

Cost: ~$1.50–2.00 with caching, ~$8 worst case. Hard budget cap is $14
by default (`--budget-cap` to override).

## What you measure

Each call records:

```json
{
  "call": 7,
  "model_key": "haiku",
  "slug": "anthropic/claude-haiku-4.5",
  "ts": 1777984789,
  "elapsed_ms": 3374,
  "input_tokens": 5964,
  "output_tokens": 200,
  "cache_read_input_tokens": 5928,
  "cache_creation_input_tokens": 0,
  "cost_usd": 0.001628,
  "provider": "Anthropic",
  "actual_cost_usd": 0.00163,
  "no_cache_cost_usd": 0.00697,
  "savings_usd": 0.00534,
  "savings_pct": 76.6
}
```

The hard ground truth is `cost_usd` (OpenRouter's billed amount).
`no_cache_cost_usd` is the hypothetical from the model's per-million
rates if every input token were billed at base rate. The delta is the
real savings.

## Findings (from a sample 389-call run, May 2026)

| Model | Cache type | Hit rate | Real savings |
|---|---|---|---|
| `claude-haiku-4.5` | explicit | 99.4% | 76.6% |
| `claude-sonnet-4.6` | explicit | 96.1% | 73.3% |
| `claude-opus-4.7` | explicit | 96.2% | **78.5%** |
| `gpt-4o-mini` (auto) | implicit | 88.2% | 41.7% |
| `gpt-4o-mini` (pinned) | implicit | **95.2%** | 44.9% |
| `gpt-5.5` | implicit | 86.4% | 61.9% |
| `gemini-2.5-flash` | explicit | 99.5% | 71.6% |
| `gemini-2.5-pro` | explicit | 96.1% | 63.4% |
| `deepseek-chat-v3.1` (Fireworks) | implicit | 96.5% | **−96.1%** |
| `llama-3.3-70b` (DeepInfra) | varies | 0.0% | 0.0% |

Five takeaways from the dataset:

1. **Anthropic models default-route via Bedrock/Vertex.** Without
   `provider.only=["Anthropic"]` the call lands on a re-router that may
   not respect `cache_control`. Pin or you measure the wrong thing.
2. **OpenAI auto-shards Azure ↔ OpenAI.** Default routing of
   `gpt-4o-mini` mixes both, breaking cache continuity between calls.
   Pinning to `OpenAI` only lifts hit rate from 88.2% to 95.2%.
3. **Llama 3.3 on DeepInfra: zero `cached_tokens`.** Even when pinned to
   a single upstream the cache field stays at 0. Provider-side, not
   shard-side.
4. **DeepSeek native unavailable on OpenRouter** for this slug. Fallback
   to Fireworks shows 96.5% cache **hits** but billed cost is 2× the
   OR-listed base rate → real savings −96%. **Cache hit rate ≠ savings.**
5. **Prefix-size scaling helps.** Same model, growing the stable
   prefix from 5.7K → 30K → 100K tokens pushes savings from 76.6% →
   79.6% → 81.5% with stable latency.

## Prefix-size scaling

```bash
python cache_lab.py --model haiku --runs 15 --system-tokens 30000 --save
python cache_lab.py --model haiku --runs 15 --system-tokens 100000 --save
```

## Provider-pin sanity test

```bash
# Was the default 88.2% hit rate due to Azure-OpenAI auto-shard?
python cache_lab.py --model gpt4o-mini --runs 30 \
    --provider-pin "OpenAI" --save
```

## Output files

| File | Purpose |
|---|---|
| `cache_lab_receipts.json` | Per-model summary entries (append-only) |
| `cache_lab_calls.jsonl` | Per-call raw rows (crash-safe append) |
| `cache_lab_budget.json` | Cumulative spend tracker (refuses to exceed cap) |
| `cache_lab_summary.md` | Auto-generated comparison table |

Generate the summary:

```bash
python cache_lab_summary.py > cache_lab_summary.md
```

A reference summary from May 2026 ships in `fixtures/sample_summary.md`.

## Tests

```bash
cd tests && PYTHONPATH=../src python -m pytest -v
```

10 tests covering usage extraction across Anthropic / OpenAI / Gemini /
no-cache shapes, cost computation, and budget safety stop.

## License

MIT — see [LICENSE](./LICENSE).
