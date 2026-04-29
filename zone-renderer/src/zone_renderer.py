"""Zone-based renderer with built-in auto-fit. Replaces freeform absolute positioning.

Architecture:
- Each template = canvas with NAMED ZONES (borders fixed in CSS).
- Each zone has overflow:hidden — content can NEVER cross borders.
- AUTOFIT_JS shrinks text font-size by linear step-down until it fits zone
  (measured via scrollHeight/scrollWidth).
- Renderer waits for autoFit to complete before screenshot.
- No judge/heal loop needed — overlap impossible by construction.

Public API:
    render_template(template_path, zones, output_png, viewport=(W, H))
        Convenience: read template, substitute {{zone_name}} placeholders
        from `zones` dict, render via Playwright.

    render(html, out_png, width=1080, height=1080, scale=2)
        Lower-level: render an already-prepared HTML string.

Both are SYNCHRONOUS wrappers around the async core (render_with_autofit).
If you're already in an event loop (Jupyter, FastAPI), call
render_with_autofit directly with `await`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

AUTOFIT_JS = """
() => {
  return new Promise((resolve) => {
    function fitOne(el) {
      const zone = el.closest('.zone');
      if (!zone) return;
      const maxW = zone.clientWidth;
      const maxH = zone.clientHeight;
      let fs = parseFloat(getComputedStyle(el).fontSize);
      const minFs = parseFloat(el.dataset.minFs || '14');
      const stepFs = parseFloat(el.dataset.stepFs || '2');
      let safety = 200;
      while ((el.scrollHeight > maxH + 1 || el.scrollWidth > maxW + 1) && fs > minFs && safety-- > 0) {
        fs -= stepFs;
        el.style.fontSize = fs + 'px';
      }
      el.dataset.fittedFs = fs.toFixed(1);
      el.dataset.minFsHit = (fs <= minFs) ? '1' : '0';
      const stillOverH = el.scrollHeight > maxH + 1;
      const stillOverW = el.scrollWidth > maxW + 1;
      el.dataset.clipped = (stillOverH || stillOverW) ? '1' : '0';
      el.dataset.overshootH = String(Math.max(0, el.scrollHeight - maxH));
      el.dataset.overshootW = String(Math.max(0, el.scrollWidth - maxW));
    }
    document.fonts.ready.then(() => {
      requestAnimationFrame(() => {
        document.querySelectorAll('[data-fit="auto"]').forEach(fitOne);
        requestAnimationFrame(() => {
          document.querySelectorAll('[data-fit="auto"]').forEach(fitOne);
          resolve(true);
        });
      });
    });
  });
}
"""


async def render_with_autofit(
    html: str,
    out_png: str | Path,
    width: int = 1080,
    height: int = 1080,
    scale: int = 2,
) -> dict:
    """Async core. Render HTML with auto-fit. Returns diagnostics dict.

    The browser is wrapped in try/finally to guarantee cleanup even when
    set_content / screenshot raises.
    """
    out_png = str(out_png)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page = await ctx.new_page()
            # domcontentloaded + fonts.ready inside AUTOFIT_JS — safer than
            # networkidle which can hang on slow CDN font loads.
            await page.set_content(html, wait_until="domcontentloaded", timeout=10000)
            # AUTOFIT_JS returns its own Promise; awaiting evaluate is sufficient.
            await page.evaluate(AUTOFIT_JS)
            fit_data = await page.evaluate("""
                () => {
                  const out = {fitted: {}, clipped: [], min_fs_hit: []};
                  document.querySelectorAll('[data-fit="auto"]').forEach(el => {
                    const zoneCls = (el.closest('.zone') || el).className.split(' ').filter(c => c.startsWith('z-')).join('.');
                    const key = zoneCls || el.tagName.toLowerCase();
                    out.fitted[key] = el.dataset.fittedFs;
                    if (el.dataset.clipped === '1') {
                      out.clipped.push({
                        zone: key, fs: el.dataset.fittedFs,
                        overshoot_h: parseInt(el.dataset.overshootH || '0'),
                        overshoot_w: parseInt(el.dataset.overshootW || '0'),
                        text: (el.innerText || '').substring(0, 60),
                      });
                    }
                    if (el.dataset.minFsHit === '1') {
                      out.min_fs_hit.push(key);
                    }
                  });
                  return out;
                }
            """)
            await page.screenshot(
                path=out_png,
                full_page=False,
                omit_background=False,
                clip={"x": 0, "y": 0, "width": width, "height": height},
            )
        finally:
            await browser.close()
    size = Path(out_png).stat().st_size
    return {
        "fitted_sizes": fit_data["fitted"],
        "clipped": fit_data["clipped"],
        "min_fs_hit": fit_data["min_fs_hit"],
        "size_bytes": size,
        "path": out_png,
    }


def render(
    html: str,
    out_png: str | Path,
    width: int = 1080,
    height: int = 1080,
    scale: int = 2,
) -> dict:
    """Sync wrapper around render_with_autofit. Do NOT call this from inside
    an existing event loop (Jupyter, FastAPI handler, async pipeline) —
    use `await render_with_autofit(...)` directly."""
    return asyncio.run(render_with_autofit(html, out_png, width, height, scale))


def render_template(
    template_path: str | Path,
    zones: dict[str, str],
    output_png: str | Path,
    viewport: tuple[int, int] = (1080, 1350),
    scale: int = 2,
) -> dict:
    """Convenience wrapper: read a template, substitute {{zone_name}}
    placeholders from `zones`, render to PNG.

    Templates use {{key}} placeholders (Mustache-style) for content
    substitution and `data-fit="auto"` plus `class="zone"` for the
    autoFit measurement.

    See examples/quote_pull.html for a complete worked template.
    """
    template_path = Path(template_path)
    html = template_path.read_text(encoding="utf-8")
    for key, value in zones.items():
        # Plain string substitution — no shell-escaping needed since this
        # only ends up in the DOM via Playwright.set_content (not any shell).
        html = html.replace(f"{{{{{key}}}}}", value)
    width, height = viewport
    return render(html, output_png, width=width, height=height, scale=scale)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: zone_renderer.py <html> <out_png> [w] [h]", file=sys.stderr)
        sys.exit(1)
    html_text = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = sys.argv[2]
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
    res = render(html_text, out, w, h)
    print(f"Rendered → {out}")
    print(f"Fitted sizes: {res['fitted_sizes']}")
    if res.get("min_fs_hit"):
        print(f"Hit min-fs: {res['min_fs_hit']}")
    if res.get("clipped"):
        print(f"CLIPPED ({len(res['clipped'])}): {res['clipped']}", file=sys.stderr)
    print(f"Size: {res['size_bytes']:,} bytes")
