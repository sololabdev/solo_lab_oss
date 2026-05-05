# RU Pulse — Russian Telegram Corpus & Analysis Engine

> Ethical, MTProto-free Russian-language Telegram corpus engine. Builds, analyses, and weekly-pulses 241 public dev / AI / diaspora / founders channels. **Zero MTProto, zero login, zero scraping of private content.** Pure `t.me/s/` HTML preview + 23-pattern prompt-injection defense + deterministic per-channel voice fingerprinting.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests: 228 passed](https://img.shields.io/badge/Tests-228%20passed-brightgreen.svg)](#testing)
[![Ruff](https://img.shields.io/badge/lint-ruff%20clean-brightgreen.svg)](https://github.com/astral-sh/ruff)
[![Status: Beta](https://img.shields.io/badge/status-beta-yellow.svg)](#)
[![Channels: 241](https://img.shields.io/badge/channels-241-informational.svg)](#)
[![Posts: 41k](https://img.shields.io/badge/posts-41%2C078-informational.svg)](#)
[![Tokens: 5.7M](https://img.shields.io/badge/tokens-5.74M-informational.svg)](#)

Builds an original linguistic corpus from public Russian-language Telegram
channels across AI/ML, dev, founders-diary, diaspora/relocant, jobs, and
product-marketing buckets. The corpus feeds research, content generation
(receipts-driven posts, voice calibration, weekly pulse reports), and AI
safety testing. v0.2 covers 41,078 posts and 5.74M tokens across 12 buckets.

## Install

```bash
git clone https://github.com/solo-lab/ru_pulse.git
cd ru_pulse
pip install -r requirements.txt

# Initialize SQLite corpus
python -m ru_pulse.storage
```

## Quick Start

```bash
# Fetch posts from 3 sample channels
python -m ru_pulse.fetch \
    --channels "neuraldeep:ai_core,addmeto:dev,durov:indie_solo" \
    --max-posts 20

# Spot-check 10 random posts
python -m ru_pulse.verify --n 10

# View corpus stats
python -m ru_pulse.verify --mode stats

# Run analysis pipeline
python -m ru_pulse.analyze
python -m ru_pulse.voice_fingerprint
python -m ru_pulse.topics

# Generate markdown report
python -m ru_pulse.dashboard

# See reports/
ls -lh reports/
```

## What You Get

**Corpus (v0.2):** 241 Russian channels across 12 community buckets (`ai_core` 33, `dev` 32, `dev_jobs_hiring` 25, `diaspora_relocant` 30, `founders_diary` 16, `hype_listicle` 28, `indie_solo` 6, `ml_aggregator` 12, `news_aggregator` 8, `product_marketing` 38, `prompt_specific` 3, `research_papers` 10) stored in local SQLite. Every post includes source URL, fetch timestamp, and `sha256(text)` hash for dedup.

**Reports:**
- `lexicon_report.json` — token frequency, Cyrillic vs. loanwords, bigram overlap
- `voice_fingerprint.json` — formality, lexicon diversity, sentiment proxy per bucket
- `topics_report.json` — cadence, bursts, cross-channel trends
- `dashboard.md` — one-pager summary (rendered from JSON receipts)

**Ethics & Legal:** Only public `t.me/s/` HTML (no MTProto, no login). Honest User-Agent. Circuit breaker for failures. Analyzed in aggregate; individual posts never republished. See [Etiquette](#etiquette).

**Live Dashboard:** ([Coming soon](https://solo-lab.dev/research/ru-pulse)) — real-time corpus metrics and trend analysis.

## How ru_pulse compares

| Capability | ru_pulse | Telethon / pyrogram | snscrape | natasha / DeepPavlov |
|---|---|---|---|---|
| Russian-first taxonomy + lexicon | ✓ | — | — | partial |
| No MTProto / no login required | ✓ | requires API_ID + phone | ✓ | n/a (offline NLP) |
| 3-layer prompt-injection defense | ✓ | — | — | — |
| Per-channel voice fingerprint (12 axes) | ✓ | — | — | — |
| Sub-corpus PMI/lift + cross-bucket Jaccard | ✓ | — | — | partial (lexical only) |
| Weekly diff-digest with brand-voice gate | ✓ | — | — | — |
| Pure-stdlib HTTP path (urllib for publish) | mostly | requests-like | requests | n/a |
| OSS-friendly: MIT, ≥108 tests, typed, py.typed | ✓ | mixed | ✓ | mixed |

ru_pulse fills a specific gap — Russian-language Telegram corpus building with safety + interpretability built in. It is not a general-purpose Telegram client (use Telethon/pyrogram for those) nor an offline NLP toolkit (use natasha/DeepPavlov for tokenisation/NER).

## What this is and is NOT

**It IS:** a polite reader of `https://t.me/s/<channel>` — the same
server-rendered HTML preview Telegram serves to anyone with a browser.

**It is NOT:**
- An MTProto / Telethon client (no API_ID, no login)
- A scraper of private channels (t.me/s/ returns 404 for those)
- A reposter or content mirror — we analyze in aggregate, attribute always

## Etiquette

- 3s + jitter delay between requests
- Honest User-Agent: `Solo-Lab-Research/0.1 (+https://solo-lab.dev/research)`
- Exponential backoff on 429/503 (30s -> 60s -> 120s -> stop)
- Circuit breaker: 3 consecutive channel failures aborts the run
- 15s request timeout

## Three-layer prompt-injection defense

1. **Pattern filter** (`sanitize.scan`) — regex on known injection
   tokens; matches go to `quarantine` table and are NEVER fed to LLMs.
2. **Structural wrap** (`sanitize.wrap_for_llm`) — every scraped post sent
   to an agent is wrapped in `<scraped_post><![CDATA[...]]></scraped_post>`
   with a system-prompt directive to treat it as third-party data.
3. **Output validator** (`sanitize.validate_output`) — best-effort scan of
   agent responses for role-break or refusal patterns.

## Layout

```
ru_pulse/
  fetch.py             # full HTTP + parser + run loop
  daily_incremental.py # watermark-based "fetch only new posts" (cron)
  sanitize.py          # 3-layer defense
  storage.py           # SQLite schema + helpers
  verify.py            # human spot-check + stats + quarantine review
  probe.py             # candidate-channel liveness check
  analyze.py           # lexicon: tokens, freq, loanword, jaccard
  voice_fingerprint.py # voice metrics + bucket centroids
  topics.py            # cadence + bursts + cross-channel zeitgeist
  dashboard.py         # markdown one-pager from JSON reports
  voice_lint.py        # CLI: score post against corpus voice fingerprints
  channels.txt         # 50-channel taxonomy (7 buckets)
  cron_daily.sh        # cron wrapper (incremental + reanalyze + TG-alert)
  data/corpus.db       # local SQLite corpus (gitignored)
  reports/             # JSON + markdown analysis artifacts
  tests/
    test_parser.py
```

## Testing

All 27 tests pass offline (no network required):

```bash
python -m pytest ru_pulse/tests/ -v
```

Tests cover:
- Parser: normal text, forwarded posts, media-only, missing msg_id
- Sanitizer: legitimate Russian passes; known injection patterns caught
- Channel parsing: file format, comma-separated input, URL/bucket injection rejected
- CDATA escape: hostile `]]>` payload remains well-formed XML
- Voice Lint: hype/broadcast/listicle/short/empty inputs each produce sane verdict

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed testing instructions.

## Channel buckets (taxonomy)

`channels.txt` ships with 50 channels across 7 buckets (counts as of v0.1.0):

| bucket            | what it is                              | n_channels | n_posts |
|-------------------|-----------------------------------------|-----------:|--------:|
| `ai_core`         | RU AI/ML focused                        | 15         | 2,545   |
| `dev`             | classic RU dev/eng community            | 10         | 1,292   |
| `hype_listicle`   | top-N hype style (anti-model)           | 5          | 949     |
| `ml_aggregator`   | paper/news aggregators                  | 5          | 813     |
| `news_aggregator` | broadcast-voice news                    | 6          | 657     |
| `indie_solo`      | RU solo-founder / relocant adjacent     | 6          | 580     |
| `prompt_specific` | narrow niche (prompt engineering)       | 3          | 324     |

## Schema (SQLite)

- `channels(name, bucket, title, first_seen_at, last_fetched)`
- `posts(channel, msg_id, posted_at, text, text_hash, views,
         forwarded_from, has_media, html_url, fetched_at, fetcher_ver)`
- `quarantine(channel, msg_id, reason, matched_pattern, matched_text,
              raw_text, flagged_at)`
- `fetch_runs(run_id, started_at, finished_at, channels_n,
              posts_new, posts_dup, posts_quarant, errors)`

## Data integrity

- Every post hashed (`sha256(text)`) for dedup + edit-detection
- Every row carries `(html_url, fetched_at, fetcher_ver)` for audit
- Spot-check protocol: random 10 posts compared with t.me UI before
  any analysis pipeline runs on the corpus

## Analysis pipeline (Phase 2)

After a fetch run, three modules produce JSON reports under `reports/`:

```bash
python -m ru_pulse.analyze            # → reports/lexicon_report.json
python -m ru_pulse.voice_fingerprint  # → reports/voice_fingerprint.json
python -m ru_pulse.topics             # → reports/topics_report.json
python -m ru_pulse.dashboard          # → reports/dashboard.md (one-pager)
```

These are deterministic — no LLM calls. They are the "receipts" layer.

LLM/agent layer reads these JSONs and produces interpreted artifacts:
- `findings.md` — receipt-worthy claims (general-purpose agent)
- `strategic_playbook.md` — positioning synthesis (solo-lab-ceo)
- `longform_draft_ru.md` — TG-ready post (content-author)
- `anti_model_bigrams.md` — voice-linter deny-list

## Continuous mode (Phase 3)

`daily_incremental.py` runs watermark-based fetch (only new posts) + recomputes
all reports. Suggested cron entry:

```cron
5 4 * * *  cd /path/to/ru_pulse && python -m ru_pulse.daily_incremental && python -m ru_pulse.analyze && python -m ru_pulse.voice_fingerprint && python -m ru_pulse.topics
```

The watermark logic in `daily_incremental.py` only refetches what's new;
typical run is 2-5 min for 50 channels. (Cron wrapper scripts are intentionally not shipped; write your own that matches your infrastructure.)

## Voice Lint CLI

Score any RU post against the 50-channel corpus voice fingerprints.

**Prerequisite:** run `python -m ru_pulse.voice_fingerprint` once to generate `reports/voice_fingerprint.json`.

```bash
# from text:
python -m ru_pulse.voice_lint --text "Я провёл три недели настраивая pipeline..."

# from file:
python -m ru_pulse.voice_lint --file posts/draft.txt

# machine-readable JSON only:
python -m ru_pulse.voice_lint --text "..." --json
```

Output:
- Nearest 3 buckets by centroid distance (`ai_core`, `hype_listicle`, etc.)
- Nearest 5 channels by per-channel fingerprint distance
- `hype_score` (0–1), `broadcast_score` (0–1), `listicle_hits`
- One-line verdict: `fits ai_core voice` / `leans hype_listicle` / etc.
