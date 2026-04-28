# structural-judge

A Python library that opens rendered HTML in headless Chromium, asks the
DOM for bounding-box geometry, and flags structural failures: text that
overflows the canvas, headlines that overlap decks, and similar layout
bugs. It is the cheap replacement for an LLM-vision quality judge — same
catches for layout bugs, $0 vs $150/mo, no API key.

## What it catches

- **Text overflow at canvas edges** — any element whose right/bottom
  bounding-box extends past the canvas dimensions (with a 4 px slack
  for sub-pixel rendering).
- **Text overlap between sibling elements** — pairwise bounding-box
  intersection check across all visible elements.

It also generates **fix suggestions** for each issue (e.g. "shrink
headline font from 64 px to 48 px so it fits"), driven by ~100 lines
of CSS-tweak heuristics.

## What it does NOT catch

- Aesthetic preferences ("the colour palette feels off")
- Brand voice ("the headline is a fact-check, not a hook")
- Visual hierarchy
- Anything you'd normally need a vision model for

For those, you still need an LLM (or a human). The structural judge is
the cheap, fast tier that runs on every render. The expensive vision
critic only runs on the renders that pass this layer.

## Why this exists

I was paying $150 in 9 days to a Gemini 2.5 Pro Vision Judge running
on every render. It worked. It was a 10× over-engineered solution for
a 1× problem.

90 % of what the vision judge caught was layout-structural — overflow,
overlap. The other 10 % was aesthetic preference, which I decided I
don't need an LLM to second-guess me on.

300 lines of Python (DOM measurement + CSS-tweak heuristics) catches
the layout bugs at $0.

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

## Use

```python
from structural_judge import judge_async

report = await judge_async(
    html=html_string,
    brief="quote pull, two-line headline + 12-word deck",
    template_name="quote_pull",
    width=1080,
    height=1080,
)

print(report["verdict"])           # "APPROVE" / "HEAL" / "REGENERATE"
print(report["overall_score"])     # 0.0 to 1.0
for issue in report["critical_issues"]:
    print(f"  - {issue}")
for fix in report["suggested_fixes"]:
    print(f"  fix: {fix['selector']}.{fix['property']} -> {fix['suggested_value']}")
```

If you're calling from sync code (no running event loop), use the sync
wrapper. It expects a PNG path with a sister `.html` file (the
convention used in the content factory pipeline this came out of):

```python
from structural_judge import judge

report = judge(
    png_path="renders/iter_1.png",   # sister iter_1.html must exist
    brief="quote pull",
    template_name="quote_pull",
)
```

You can also pass `html` directly and skip the sister-file convention:

```python
report = judge(
    png_path="renders/iter_1.png",
    brief="quote pull",
    template_name="quote_pull",
    html=html_string,
)
```

## CLI

For one-off probes:

```bash
python src/structural_judge.py path/to/page.html quote_pull "brief description"
```

Outputs the report dict as JSON.

## Public API surface

| Function | When to use |
|---|---|
| `judge_async(html, brief, template_name, width, height)` | Async core. From inside an event loop. |
| `judge(png_path, brief, template_name, width, height, html=None)` | Sync wrapper. From plain scripts. |

Both return:

```python
{
  "verdict": "APPROVE" | "HEAL" | "REGENERATE",
  "overall_score": 0.0..1.0,
  "critical_issues": [str, ...],
  "suggested_fixes": [{"selector", "property", "current_value",
                       "suggested_value", "reason"}, ...],
  "checks": {"text_overflow": bool, "text_overlap": bool},
  "element_count": int,
  "_layout": {...},   # raw DOM measurements (debug; large)
}
```

## Limits / known sharp edges

- The overlap heuristic doesn't currently special-case flex siblings —
  intentional overlaps (badges, callouts) may register as bugs.
- `score_from_issues` weights overflow more than overlap by design;
  tune the formula in `score_from_issues()` if your priorities differ.
- `_layout` is included in the return dict for debugging; it can be
  large (one entry per element) — strip it before logging in prod.
- `judge()` calls `asyncio.run()` internally — DO NOT call from inside
  an existing event loop.

## License

MIT. Part of the Solo Lab open-source pile.
