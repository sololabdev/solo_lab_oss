# Solo Lab — open-source pile

Faceless AI-инфра for solo founders. **$30/мес** runs the entire content
pipeline. Receipts, не маркетинг.

[solo-lab.dev](https://solo-lab.dev) · [t.me/sololabru](https://t.me/sololabru) · [x.com/solo_lab_dev](https://x.com/solo_lab_dev)

This repo is the public open-source pile from the Solo Lab content
infrastructure — four small, focused libraries / datasets, each replacing
a $50–150/mo SaaS or filling a niche where no good open thing existed.

---

## Five projects in one repo

| Project | What it does | License |
|---|---|---|
| **[`zone-renderer/`](./zone-renderer)** | HTML template + zones dict → 1080×1350 PNG via Playwright + autoFit JS. Replaces Bannerbear/Placid ($49–99/mo). | MIT |
| **[`structural-judge/`](./structural-judge)** | DOM-based layout quality judge. Catches text overflow + overlap. Replaces an LLM-vision judge that cost me $150 in 9 days. | MIT |
| **[`opus-4-7-context-test/`](./opus-4-7-context-test)** | Reproducible benchmark for Anthropic Claude Opus 4.7's effective context length. 30 questions × 3 sizes. Backs [solo-lab.dev/posts/opus-4-7-context-cliff](https://solo-lab.dev/posts/opus-4-7-context-cliff). | MIT |
| **[`cache-lab/`](./cache-lab)** | Stdlib-only benchmark of real prompt-cache hit rate + billed savings across 10 production LLMs via OpenRouter. 389 calls × $1.79 = receipts table for "90% off cached input" claim. | MIT |
| **[`ru-pulse/`](./ru-pulse)** | Open RU-Telegram corpus + analytics. 7,405 posts from 50 channels (RU dev / AI / релокант diaspora). Reproducible scrape, weekly digest scripts, citable via `CITATION.cff`. | MIT |

---

## Per-project quick start

### zone-renderer

```bash
cd zone-renderer
pip install -r requirements.txt
playwright install chromium
python examples/render_example.py
# Renders examples/quote_pull.html with two zones populated, writes a PNG.
```

```python
from zone_renderer import render_template

result = render_template(
    template_path="examples/quote_pull.html",
    zones={"headline": "...", "deck": "..."},
    output_png="out.png",
    viewport=(1080, 1350),
)
```

### structural-judge

```bash
cd structural-judge
pip install -r requirements.txt
playwright install chromium
python src/structural_judge.py path/to/page.html template_name "brief"
```

```python
from structural_judge import judge_async

report = await judge_async(html=html_string, brief="...",
                           template_name="quote_pull",
                           selectors=[".headline", ".deck"])
print(report["verdict"])  # APPROVE / HEAL / REGENERATE
```

### opus-4-7-context-test

```bash
cd opus-4-7-context-test
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # or OPENROUTER_API_KEY
cd src
python context_loader.py --offline
python benchmark_opus_47.py --dry-run      # validate, no API calls
python benchmark_opus_47.py                # full run, ~$8 with caching, ~30 min
python score_run.py <run_id>
python report_run.py <run_id>
```

Ships a small fixture (`fixtures/sample_repo/` + 9 sample questions) so
the benchmark works on a fresh clone. To benchmark your own codebase,
point at `--corpus-dir /your/repo` and write your own `questions.json`.

### ru-pulse

```bash
cd ru-pulse
pip install -r requirements.txt
python -m ru_pulse.collect --channels seed.json --out posts/
python -m ru_pulse.weekly_pulse posts/ --week 2026-W18
```

Open RU-Telegram corpus: 7,405 posts across 50 channels (dev / AI /
релокант diaspora), refreshed weekly. The package ships the seed-channel
list, the collector, the weekly-digest analytics, and tests against
fixture data. `CITATION.cff` makes it citable for research; license is
MIT for code, content remains under each channel author's terms (see
`SECURITY.md`).

---

## Stack receipts ($32/mo — actual numbers)

| Line item | Cost/mo | What I'm getting |
|---|---|---|
| Hostinger VPS | $4.50 | Ubuntu, 4 GB RAM, runs everything |
| ElevenLabs Creator | $22.00 | TTS + STT for daily reels |
| Anthropic API (with caching) | ~$5.00 | Sonnet 4.6 daily script writing |
| Cloudflare domain | ~$1.00 (amortized) | solo-lab.dev |
| Postiz, Beehiiv free, Telegram, GitHub, ffmpeg, Playwright | $0 | |
| **Total** | **$32.50** | |

Full breakdown + how I killed each $20–150/mo SaaS bill:
[solo-lab.dev/receipts](https://solo-lab.dev/receipts).

---

## Why one repo, four projects

These projects grew out of the same content infrastructure and share an
aesthetic: small, single-file, replace-a-SaaS, no async magic when sync
works. They're packaged in one repo for one URL to remember and one
issue tracker. Each has its own README, requirements.txt, and LICENSE;
pick whichever is useful and ignore the rest.

`ru-pulse` is the odd one out — it's a dataset + scripts, not a SaaS
replacement. Lives here so research-side readers don't need to clone a
second repo, and the LICENSE/CITATION/SECURITY artifacts already match
the rest of the pile.

---

## License

MIT across the board. Use it. Fork it. If you build something nice with
it I'd like to see — [t.me/sololabru](https://t.me/sololabru) or
[x.com/solo_lab_dev](https://x.com/solo_lab_dev).
