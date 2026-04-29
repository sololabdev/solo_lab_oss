"""Unit tests for the pure (Playwright-free) parts of zone_renderer.

The async render path needs Chromium and is exercised by examples/render_example.py;
these tests pin the substitution + module surface so regressions in the
template-handling layer are caught without firing up a browser."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import zone_renderer


def test_autofit_js_is_well_formed_string() -> None:
    js = zone_renderer.AUTOFIT_JS
    assert isinstance(js, str)
    assert "data-fit" in js
    assert "scrollHeight" in js
    assert "fonts.ready" in js


def test_render_template_substitutes_zones(tmp_path, monkeypatch) -> None:
    template = tmp_path / "tpl.html"
    template.write_text(
        '<div class="zone"><span data-fit="auto">{{headline}}</span></div>'
        '<div class="zone"><span data-fit="auto">{{deck}}</span></div>',
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_render(html, out_png, width=1080, height=1080, scale=2):
        captured["html"] = html
        captured["out_png"] = out_png
        captured["width"] = width
        captured["height"] = height
        return {"path": str(out_png), "size_bytes": 0, "fitted_sizes": {}, "clipped": []}

    monkeypatch.setattr(zone_renderer, "render", fake_render)

    out = tmp_path / "out.png"
    zone_renderer.render_template(
        template_path=template,
        zones={"headline": "Hello", "deck": "World"},
        output_png=out,
        viewport=(1200, 1500),
    )

    assert "Hello" in captured["html"]
    assert "World" in captured["html"]
    assert "{{headline}}" not in captured["html"]
    assert "{{deck}}" not in captured["html"]
    assert captured["width"] == 1200
    assert captured["height"] == 1500


def test_render_template_leaves_unknown_placeholders_alone(tmp_path, monkeypatch) -> None:
    template = tmp_path / "tpl.html"
    template.write_text("<p>{{absent}} and {{present}}</p>", encoding="utf-8")
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        zone_renderer, "render",
        lambda html, *a, **k: captured.update(html=html) or {"path": "", "size_bytes": 0, "fitted_sizes": {}, "clipped": []},
    )
    zone_renderer.render_template(template, {"present": "X"}, tmp_path / "o.png")
    assert "X" in captured["html"]
    assert "{{absent}}" in captured["html"]
