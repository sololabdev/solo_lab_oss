"""Worked example: render `quote_pull.html` with headline + deck populated.

Run from the repo root:
    pip install -r requirements.txt
    playwright install chromium
    python examples/render_example.py

Produces `examples/output/quote_pull.png`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/zone_renderer.py importable without installation.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from zone_renderer import render_template  # noqa: E402


def main() -> None:
    template = HERE / "quote_pull.html"
    out_dir = HERE / "output"
    out_dir.mkdir(exist_ok=True)
    output_png = out_dir / "quote_pull.png"

    result = render_template(
        template_path=template,
        zones={
            "headline": "I cut my AI infra bill from $300 to $30.",
            "deck": "What I removed and why — receipts, не маркетинг.",
        },
        output_png=output_png,
        viewport=(1080, 1350),
    )

    print(f"OK: rendered → {result['path']}")
    print(f"size: {result['size_bytes']:,} bytes")
    print(f"fitted font sizes: {result['fitted_sizes']}")
    if result.get("clipped"):
        print(f"WARN: {len(result['clipped'])} zone(s) still clipped after autoFit:",
              file=sys.stderr)
        for c in result["clipped"]:
            print(f"  - {c['zone']}: '{c['text']}…' "
                  f"(overshoot h={c['overshoot_h']}px w={c['overshoot_w']}px)",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
