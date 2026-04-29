"""Deterministic structural judge — uses Playwright to extract element bounding boxes,
detects overflow/overlap WITHOUT LLM. Faster + free + more reliable for layout.

Returns the same JSON shape as any compatible judge so callers can swap
implementations behind a single interface."""
from __future__ import annotations
import asyncio, json, sys, pathlib, re
from playwright.async_api import async_playwright


def _parse_px(value: str | None, default: int = 0) -> int:
    """Parse a CSS px-style value safely. Returns `default` on '', 'normal',
    'auto', or any unrecognised input. Never raises on common CSS like
    `line-height: normal` or `bottom: auto`."""
    if not value:
        return default
    m = re.match(r"(\d+)", str(value))
    return int(m.group(1)) if m else default

# Element selectors we care about for editorial templates
TRACKED_SELECTORS = [
    ".headline", ".deck", ".kicker", ".subline", ".subtext",
    ".meta", ".meta-top", ".date-top", ".brand", ".brand-top",
    ".handle", ".handle-bar", ".tag", ".tag-bar", ".swipe", ".read-more",
    ".byline", ".label-1", ".label-2", ".giant-stat", ".compare-stat",
    ".divider", ".bar-top", ".bar-bottom", ".bottom-bar",
    ".quote", ".quote-mark", ".headline .em",
]

# JS to extract rects + check edge clipping per element
EXTRACT_JS = """
(selectors) => {
  const canvas = document.querySelector('.stage') || document.body;
  const cw = canvas.offsetWidth || window.innerWidth;
  const ch = canvas.offsetHeight || window.innerHeight;
  const out = {canvas: {width: cw, height: ch}, elements: []};
  let uid = 0;
  const allEls = [];
  selectors.forEach(sel => {
    document.querySelectorAll(sel).forEach((el, i) => {
      el.setAttribute('data-cej-uid', String(uid));
      const r = el.getBoundingClientRect();
      const cs = window.getComputedStyle(el);
      const rec = {
        uid: uid,
        selector: sel,
        index: i,
        text: (el.innerText || '').substring(0, 80),
        x: Math.round(r.left), y: Math.round(r.top),
        w: Math.round(r.width), h: Math.round(r.height),
        right: Math.round(r.right), bottom: Math.round(r.bottom),
        font_size: cs.fontSize,
        line_height: cs.lineHeight,
        color: cs.color,
        position_kind: cs.position,
        css_top: cs.top,
        css_bottom: cs.bottom,
        anchor: (cs.bottom !== 'auto' && cs.top === 'auto') ? 'bottom' :
                (cs.top !== 'auto' && cs.bottom === 'auto') ? 'top' : 'mixed',
        ancestor_uids: [],
      };
      allEls.push({el, rec});
      uid++;
    });
  });
  // For each element, list ancestor UIDs (so we can skip parent-child overlap)
  allEls.forEach(({el, rec}) => {
    let p = el.parentElement;
    while (p) {
      const puid = p.getAttribute && p.getAttribute('data-cej-uid');
      if (puid !== null && puid !== undefined && puid !== '') {
        rec.ancestor_uids.push(parseInt(puid));
      }
      p = p.parentElement;
    }
    out.elements.push(rec);
  });
  return out;
}
"""


async def extract_layout(html: str, width: int, height: int,
                         selectors: list[str] | None = None) -> dict:
    """Render HTML and return element rect data.

    `selectors` defaults to the bundled TRACKED_SELECTORS — a list tuned
    for the content factory this judge came out of. Pass your own list
    of CSS selectors (e.g. `["h1", "h2", "p", ".caption"]`) to use this
    against templates with different class conventions.
    """
    sel_list = selectors if selectors is not None else TRACKED_SELECTORS
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context(viewport={"width": width, "height": height})
            page = await ctx.new_page()
            # domcontentloaded + fonts.ready below; networkidle hangs on slow CDN fonts
            await page.set_content(html, wait_until="domcontentloaded", timeout=10000)
            await page.evaluate("document.fonts.ready")
            layout = await page.evaluate(EXTRACT_JS, sel_list)
        finally:
            await browser.close()
        return layout


def detect_issues(layout: dict, width: int, height: int) -> tuple[list[str], list[dict]]:
    """Return (critical_issues[], suggested_fixes[])."""
    issues = []
    fixes = []
    elements = layout["elements"]

    # 1. Edge-clipping detection
    for e in elements:
        if not e["text"]:
            continue
        # Allow 4px slack for sub-pixel rendering
        if e["right"] > width + 4:
            overshoot = e["right"] - width
            issues.append(f"'{e['selector']}' (text: '{e['text'][:30]}...') extends {overshoot}px past right edge")
            # Suggest font shrink: reduce by ~overshoot/total_width %
            cur_fs = _parse_px(e["font_size"])
            new_fs = max(40, int(cur_fs * (1 - (overshoot / width) - 0.05)))
            fixes.append({
                "selector": e["selector"],
                "property": "font-size",
                "current_value": e["font_size"],
                "suggested_value": f"{new_fs}px",
                "reason": f"text overshoots right edge by {overshoot}px, shrink to fit",
            })
        if e["bottom"] > height + 4:
            overshoot = e["bottom"] - height
            issues.append(f"'{e['selector']}' extends {overshoot}px past bottom edge")
        if e["x"] < -4 or e["y"] < -4:
            issues.append(f"'{e['selector']}' starts off-canvas ({e['x']},{e['y']})")

    # 2. Overlap detection (between text elements)
    text_els = [e for e in elements if e["text"] and e["w"] > 0 and e["h"] > 0]
    seen = set()
    proposed_fixes = {}  # dedupe fixes by (selector, property), keep most aggressive
    for i, a in enumerate(text_els):
        for b in text_els[i+1:]:
            # Skip same-selector siblings (.headline .em x N)
            if a["selector"] == b["selector"] and a["index"] != b["index"]:
                continue
            # Skip nested .em inside .headline (textual containment)
            if a["selector"] in b["selector"] or b["selector"] in a["selector"]:
                continue
            # Skip true parent-child via DOM ancestor check (.handle inside .bottom-bar)
            if a["uid"] in b.get("ancestor_uids", []) or b["uid"] in a.get("ancestor_uids", []):
                continue
            # Skip if both share an ancestor that's a flex container (siblings inside flex layout)
            common_ancestors = set(a.get("ancestor_uids", [])) & set(b.get("ancestor_uids", []))
            # Compute intersection
            ix = max(0, min(a["right"], b["right"]) - max(a["x"], b["x"]))
            iy = max(0, min(a["bottom"], b["bottom"]) - max(a["y"], b["y"]))
            if ix < 8 or iy < 8:
                continue

            key = tuple(sorted([a["selector"], b["selector"]]))
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                f"OVERLAP: '{a['selector']}' (y={a['y']}-{a['bottom']}) and "
                f"'{b['selector']}' (y={b['y']}-{b['bottom']}) overlap {ix}x{iy}px"
            )

            # Identify roles by selector heuristic
            def is_bottom_anchored(el):
                # Trust DOM anchor first, fall back to selector convention
                if el["anchor"] == "bottom":
                    return True
                bottom_anchored_names = ("deck", "bottom-bar", "handle", "swipe", "tag", "byline", "read-more")
                return any(n in el["selector"] for n in bottom_anchored_names)

            headline_el = a if "headline" in a["selector"] and "em" not in a["selector"] else (
                b if "headline" in b["selector"] and "em" not in b["selector"] else None)
            deck_el = a if ("deck" in a["selector"] or "subtext" in a["selector"]) else (
                b if ("deck" in b["selector"] or "subtext" in b["selector"]) else None)

            # MIN_DECK_BOTTOM: safe distance from typical bottom-bar (handle/tag at bottom:14-90)
            MIN_DECK_BOTTOM = 120  # px — leaves 30+ px gap above bottom-bar

            # Strategy B: push deck DOWN if there's safe room (cap at MIN_DECK_BOTTOM)
            push_achieved = 0
            if deck_el and is_bottom_anchored(deck_el):
                cur_bottom_match = re.match(r"(\d+)", deck_el["css_bottom"])
                if cur_bottom_match:
                    cur_b = int(cur_bottom_match.group(1))
                    if cur_b > MIN_DECK_BOTTOM:
                        shift = min(iy + 20, cur_b - MIN_DECK_BOTTOM)
                        new_b = cur_b - shift
                        push_achieved = shift
                        fix_key = (deck_el["selector"], "bottom")
                        proposed_fixes[fix_key] = {
                            "selector": deck_el["selector"],
                            "property": "bottom",
                            "current_value": deck_el["css_bottom"],
                            "suggested_value": f"{new_b}px",
                            "reason": f"push deck {shift}px down (bottom {cur_b}→{new_b}, capped at min {MIN_DECK_BOTTOM}px) to clear {iy}px overlap",
                        }

            # Strategy A: shrink headline to cover REMAINING overlap not handled by push
            remaining_overlap = max(0, iy - push_achieved)
            if headline_el and remaining_overlap > 8:
                cur_fs = _parse_px(headline_el["font_size"])
                # Shrink proportional to remaining overlap
                shrink_pct = min(0.35, max(0.12, (remaining_overlap / max(headline_el["h"], 1)) + 0.05))
                # Floor at 48 (smaller for crowded layouts), and ensure min -8px progress per iter
                computed = int(cur_fs * (1 - shrink_pct))
                forced_progress = cur_fs - 8
                new_fs = max(48, min(computed, forced_progress))
                if new_fs >= cur_fs:  # safety
                    new_fs = max(48, cur_fs - 8)
                fix_key = (headline_el["selector"], "font-size")
                if fix_key not in proposed_fixes or _parse_px(proposed_fixes[fix_key]["suggested_value"]) > new_fs:
                    proposed_fixes[fix_key] = {
                        "selector": headline_el["selector"],
                        "property": "font-size",
                        "current_value": headline_el["font_size"],
                        "suggested_value": f"{new_fs}px",
                        "reason": f"shrink headline {int(shrink_pct*100)}% to clear remaining {remaining_overlap}px overlap (push {push_achieved}px)",
                    }

            # Strategy C: no headline in this collision — shrink the "soft" body element
            # (deck/subtext, multi-line wrapping). Applies to subline×deck, kicker×deck, etc.
            # We shrink whichever element is taller and uses smaller fs (so it's text-body, not display).
            if not headline_el and remaining_overlap > 8:
                def soft_score(el):
                    fs = _parse_px(el["font_size"])
                    return el["h"] / max(fs, 1)  # higher = more lines = softer body
                soft_el = max((a, b), key=soft_score)
                cur_fs = _parse_px(soft_el["font_size"])
                # Each line removed via shrink ~= line-height * fs. We aim to drop just over remaining_overlap.
                shrink_pct = min(0.30, max(0.10, remaining_overlap / max(soft_el["h"], 1) + 0.04))
                computed = int(cur_fs * (1 - shrink_pct))
                forced_progress = cur_fs - 2
                new_fs = max(16, min(computed, forced_progress))
                if new_fs >= cur_fs:
                    new_fs = max(16, cur_fs - 2)
                fix_key = (soft_el["selector"], "font-size")
                if fix_key not in proposed_fixes or _parse_px(proposed_fixes[fix_key]["suggested_value"]) > new_fs:
                    proposed_fixes[fix_key] = {
                        "selector": soft_el["selector"],
                        "property": "font-size",
                        "current_value": soft_el["font_size"],
                        "suggested_value": f"{new_fs}px",
                        "reason": f"shrink {soft_el['selector']} {int(shrink_pct*100)}% to clear {remaining_overlap}px overlap (no headline; push {push_achieved}px)",
                    }

    fixes.extend(proposed_fixes.values())

    # 3. Bottom-bar elements outside canvas (.bar-bottom should be at y >= height-h)
    return issues, fixes


def score_from_issues(issues: list[str], elements_count: int) -> float:
    """Score based on overlap severity (parsed from issue strings)."""
    if not issues:
        return 1.0
    total_overlap_pixels = 0
    for issue in issues:
        m = re.search(r"(\d+)x(\d+)px", issue)
        if m:
            total_overlap_pixels += int(m.group(1)) * int(m.group(2))
    # 0 overlap = 1.0, 100K px² = 0.5, 500K+ px² = 0.0
    if total_overlap_pixels == 0:
        return max(0.5, 1.0 - len(issues) * 0.05)
    score = max(0.0, 1.0 - (total_overlap_pixels / 200_000))
    return round(score, 2)


async def judge_async(html: str, brief: str, template_name: str,
                      width: int = 1080, height: int = 1080,
                      selectors: list[str] | None = None) -> dict:
    """Run the structural judge against rendered HTML.

    `selectors`: optional list of CSS selectors to track. If None, uses
    the bundled TRACKED_SELECTORS list (tuned for `.headline`, `.deck`,
    etc.). Override for templates with different class conventions.
    """
    layout = await extract_layout(html, width, height, selectors=selectors)
    issues, fixes = detect_issues(layout, width, height)
    score = score_from_issues(issues, len(layout["elements"]))
    verdict = ("APPROVE" if score >= 0.85 and not issues else
               "HEAL" if fixes else
               "REGENERATE")
    return {
        "overall_score": round(score, 2),
        "critical_issues": issues,
        "suggested_fixes": fixes,
        "verdict": verdict,
        "checks": {
            "text_overflow": any("past" in i and "edge" in i for i in issues),
            "text_overlap": any("OVERLAP" in i for i in issues),
        },
        "element_count": len(layout["elements"]),
        "_layout": layout,  # debug
    }


def judge(png_path: str, brief: str, template_name: str,
          width: int = 1080, height: int = 1080,
          html: str | None = None) -> dict:
    """Synchronous wrapper. Two call modes:

    - Pass html directly (preferred) — png_path is unused but kept for
      back-compat with callers that use it for filename hints.
    - Pass only png_path — html is recovered from the sister .html file
      next to the PNG (e.g. iter_N.png alongside iter_N.html).
    """
    if html is None:
        html_path = pathlib.Path(png_path).with_suffix(".html")
        if not html_path.exists():
            raise ValueError(f"Need either html arg or sister file {html_path}")
        html = html_path.read_text(encoding="utf-8")
    return asyncio.run(judge_async(html, brief, template_name, width, height))


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: structural_judge.py <html_path> <template_name> <brief> [w] [h]", file=sys.stderr)
        sys.exit(1)
    html_path = sys.argv[1]
    name = sys.argv[2]
    brief = " ".join(sys.argv[3:4])
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
    h = int(sys.argv[5]) if len(sys.argv) > 5 else 1080
    html = pathlib.Path(html_path).read_text()
    report = asyncio.run(judge_async(html, brief, name, w, h))
    # Drop _layout for cleaner stdout
    debug_layout = report.pop("_layout", None)
    print(json.dumps(report, indent=2, ensure_ascii=False))
