# zone-renderer

A small Python library that turns an HTML template + a dict of named
zone contents into a 1080×1350 (or any size) PNG. Replaces SaaS
templating tools like Bannerbear and Placid for templated social
creatives.

Headless Chromium does the rendering. An embedded JavaScript autoFit
pass shrinks each zone's font-size by linear step-down until the
content fits its bounding box — overflow becomes impossible by
construction, no layout judge needed.

## Why this exists

The content factory I run produces a daily 1080×1350 hero creative.
Three options for templated rendering:

1. Bannerbear / Placid — $49–99/mo. Works, but adds a SaaS dependency
   for something that's HTML + a bit of JS.
2. Build a node/canvas renderer — overkill for "render an HTML page,
   screenshot it."
3. Playwright + a ~50-line autoFit JS.

This is option 3.

## Install

Requires Python 3.10+.

```bash
pip install -r requirements.txt
playwright install chromium
```

## Use

```python
from zone_renderer import render_template

result = render_template(
    template_path="examples/quote_pull.html",
    zones={
        "headline": "I cut my AI infra bill from $300 to $30.",
        "deck": "What I removed and why — receipts, не маркетинг.",
    },
    output_png="out.png",
    viewport=(1080, 1350),
)

print(result["fitted_sizes"])  # final font sizes after autoFit
print(result["clipped"])       # zones still over-spilling at min font size
```

If you're already inside an event loop (Jupyter, FastAPI, async
pipeline), use the async core directly:

```python
from zone_renderer import render_with_autofit

result = await render_with_autofit(html_string, "out.png", 1080, 1350)
```

## Templates

Templates are ordinary HTML/CSS files. Two conventions:

1. **Mustache placeholders** — `{{key}}` strings that match keys in
   the `zones` dict get substituted. No partials, no logic, just plain
   string replacement.

2. **autoFit zones** — wrap content elements with `class="zone"` (the
   bounding box) and an inner element with `data-fit="auto"` (the text
   that gets shrunk). Optional `data-min-fs` (minimum font-size in px,
   default 14) and `data-step-fs` (shrink step in px, default 2).

A worked example is at `examples/quote_pull.html`. Run
`python examples/render_example.py` to see it produce a PNG end-to-end.

## End-to-end example

```bash
git clone https://github.com/sololabdev/solo_lab_oss
cd solo_lab_oss/zone-renderer
pip install -r requirements.txt
playwright install chromium

python examples/render_example.py
# OK: rendered → examples/output/quote_pull.png
# size: 24,361 bytes
# fitted font sizes: {'z-headline': '78.0', 'z-deck': '32.0'}
```

## Public API surface

| Function | When to use |
|---|---|
| `render_template(template_path, zones, output_png, viewport, scale)` | Convenience: read template, substitute `{{zones}}`, render. |
| `render(html, out_png, width, height, scale)` | Lower-level: pre-prepared HTML string. Sync. |
| `render_with_autofit(html, out_png, width, height, scale)` | Async core. Use this if you're already in an event loop. |

## Limits / known sharp edges

- Single zone-fit class only (`.zone`); nested zones aren't supported.
- AutoFit shrinks linearly, not via binary search — measurably ~30 ms
  slower per render but trivial in absolute terms (~80 ms vs ~50 ms
  for a single creative).
- Templates that load remote fonts will block on `domcontentloaded`
  for up to 10 s; bundle web fonts locally for fastest renders.
- `render()` calls `asyncio.run()` internally — DO NOT call from
  inside an existing event loop.

## License

MIT. Use it. Fork it. If you build something nice with it I'd like to
see — [t.me/sololabru](https://t.me/sololabru) or
[x.com/solo_lab_dev](https://x.com/solo_lab_dev).
