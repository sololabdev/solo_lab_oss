# Cache Lab — Multi-Model Benchmark Summary

_Generated: 2026-05-05 13:43 UTC_

- **Models tested:** 10
- **Total calls:** 389
- **Total spend:** $1.7880
- **Default stable prefix:** ~5,772 tokens (BRAND.md proxy); scaling rows below at 30K and 100K
- **User messages:** 10 base, cycled per run

## Comparison table

| Model | Cache type | Provider | Runs | Hit rate | Total savings | Actual $ | No-cache $ |
|---|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-4.5` | explicit | Anthropic | 30/30 |  99.4% |  76.6% | $0.0488 | $0.2089 |
| `anthropic/claude-sonnet-4.6` | explicit | Anthropic | 30/30 |  96.1% |  73.3% | $0.1674 | $0.6267 |
| `anthropic/claude-opus-4.7` | explicit | Anthropic | 30/30 |  96.2% |  78.5% | $0.3839 | $1.7870 |
| `openai/gpt-4o-mini` | implicit | Azure, OpenAI | 30/30 |  88.2% |  41.7% | $0.0131 | $0.0224 |
| `openai/gpt-4o` | implicit | Azure, OpenAI | 30/30 |  76.6% |  31.6% | $0.2545 | $0.3722 |
| `openai/gpt-5.5` | implicit | OpenAI | 30/30 |  86.4% |  61.9% | $0.3368 | $0.8852 |
| `google/gemini-2.5-flash` | explicit | Google | 29/30 |  99.5% |  71.6% | $0.0138 | $0.0485 |
| `google/gemini-2.5-pro` | explicit | Google | 30/30 |  96.1% |  63.4% | $0.0832 | $0.2277 |
| `deepseek/deepseek-chat-v3.1` | implicit | Fireworks | 30/30 |  96.5% | -96.1% | $0.0539 | $0.0275 |
| `meta-llama/llama-3.3-70b-instruct` | varies | AkashML, DeepInfra, Inceptron, Nebius, Novita, Parasail | 30/30 |   3.3% | -17.6% | $0.0206 | $0.0175 |

## Notable observations

- **`anthropic/claude-haiku-4.5`** — first call hit cache (warm prefix from prior session); 100% cache hit across all calls; avg latency 3049ms.
- **`anthropic/claude-sonnet-4.6`** — first call wrote 5,929 tokens to cache; avg latency 5233ms.
- **`anthropic/claude-opus-4.7`** — first call wrote 10,864 tokens to cache; avg latency 5615ms.
- **`openai/gpt-4o-mini`** — 2 mid-run cache misses (TTL eviction); avg latency 1776ms.
- **`openai/gpt-4o`** — 3 mid-run cache misses (TTL eviction); avg latency 1831ms.
- **`openai/gpt-5.5`** — 1 mid-run cache misses (TTL eviction); avg latency 5895ms.
- **`google/gemini-2.5-flash`** — first call wrote 4,478 tokens to cache; first call hit cache (warm prefix from prior session); 100% cache hit across all calls; avg latency 1755ms.
- **`google/gemini-2.5-pro`** — avg latency 4003ms.
- **`deepseek/deepseek-chat-v3.1`** — first call hit cache (warm prefix from prior session); 100% cache hit across all calls; avg latency 3571ms.
- **`meta-llama/llama-3.3-70b-instruct`** — 28 mid-run cache misses (TTL eviction); avg latency 4051ms.

## Prefix-size scaling — `claude-haiku-4.5`

How does cache savings scale with stable prefix size? Same model, same provider pin, varying system prompt token count.

| Prefix tokens | Runs | Hit rate | Real savings | Actual $/call | No-cache $/call | Latency |
|---|---|---|---|---|---|---|
| ~ 5,772 | 30/30 |  99.4% |  76.6% | $0.00163 | $0.00696 | 3049ms |
| ~30,000 | 15/15 |  93.2% |  79.6% | $0.00644 | $0.03163 | 3088ms |
| ~99,987 | 15/15 |  93.3% |  81.5% | $0.01903 | $0.10289 | 3491ms |

## Pin-override sanity tests

Re-runs with `--provider-pin <X>` to test the auto-shard hypothesis.

| Model | Pin | Hit rate | Savings | Actual $ | Notes |
|---|---|---|---|---|---|
| `openai/gpt-4o-mini` | OpenAI (got: OpenAI) |  95.2% |  44.9% | $0.0123 | 1/30 misses |
| `meta-llama/llama-3.3-70b-instruct` | DeepInfra (got: DeepInfra) |   0.0% |   0.0% | $0.0176 | 30/30 misses |

## Open questions answered by this dataset

1. **Same vs different user message** — answered by raw call log
   (`cache_lab_calls.jsonl`); user_msg_preview lets you group by hash.

2. **Hit rate by prefix size** — partially answered. All runs use a
   ~5.8K-token prefix; rerun with `--system-tokens 30k` for scaling.

3. **OpenAI implicit caching consistency** — see gpt-4o-mini / gpt-4o /
   gpt-5.5 rows above. Cache fields populated only when prefix ≥1024
   tokens AND the same prefix has been seen recently.

4. **Gemini implicit cache** — see gemini-flash / gemini-pro. Their
   `prompt_tokens_details.cached_tokens` fires only at certain sizes.

5. **OpenRouter cross-region routing** — provider column in the table
   above shows where each call landed. Anthropic + Google + DeepSeek
   were force-pinned via `provider.only`; others were auto-routed.

## Receipts

- Per-call rows: `cache_lab_calls.jsonl` (300+ rows)
- Per-model summaries: `cache_lab_receipts.json`
- Cumulative budget: `cache_lab_budget.json`
