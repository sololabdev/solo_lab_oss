"""Render a markdown one-pager dashboard from the JSON reports.

Used as the email/TG-ready daily summary, or as a quick eyeball for
humans before any agent touches the data.
"""
from __future__ import annotations

import json
from pathlib import Path

REPORTS = Path(__file__).parent / "reports"


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def render() -> str:
    lex_path = REPORTS / "lexicon_report.json"
    voice_path = REPORTS / "voice_fingerprint.json"
    topics_path = REPORTS / "topics_report.json"
    if not (lex_path.exists() and voice_path.exists() and topics_path.exists()):
        return "[dashboard] reports missing; run analyze + voice_fingerprint + topics first.\n"

    lex = json.loads(lex_path.read_text())
    voice = json.loads(voice_path.read_text())
    topics = json.loads(topics_path.read_text())

    out: list[str] = []
    out.append("# RU Pulse — daily dashboard\n")
    out.append(f"_generated_at: `{lex['generated_at']}` · "
               f"channels: {lex['corpus']['channels']} · "
               f"posts: {lex['corpus']['posts']:,} · "
               f"tokens: {lex['corpus']['tokens']:,}_\n")

    out.append("## Per-bucket lexicon")
    out.append("")
    out.append("| bucket | n_ch | n_posts | loanword | code-switch |")
    out.append("|---|---:|---:|---:|---:|")
    for b, d in sorted(lex["per_bucket"].items(), key=lambda kv: -kv[1]["n_posts"]):
        out.append(f"| `{b}` | {d['n_channels']} | {d['n_posts']} | "
                   f"{_fmt_pct(d['loanword_share'])} | {_fmt_pct(d['code_switching_rate'])} |")

    out.append("\n## Voice — bucket centroids (normalized 0..1)")
    out.append("")
    out.append("| bucket | excl/100w | q/100w | emoji/post | caps/100w | 1stPP/100w | listicle | long-post |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for b, d in sorted(voice["bucket_centroids"].items()):
        c = d["centroid"]
        out.append(
            f"| `{b}` | {c['exclam_per_100w']} | {c['question_per_100w']} | "
            f"{c['emoji_per_post']} | {c['caps_per_100w']} | "
            f"{c['first_person_per_100w']} | {c['listicle_share']} | "
            f"{c['long_post_share']} |"
        )

    out.append("\n## Top cross-channel similarity (jaccard, top 10)")
    out.append("")
    for s in lex["cross_channel_similarity_top"][:10]:
        out.append(f"- `{s['a']}` ↔ `{s['b']}` — {s['jaccard']}")

    out.append("\n## Zeitgeist last 28d (terms in ≥10 channels, top 25)")
    out.append("")
    z = [t for t in topics["cross_channel_zeitgeist_28d"]
         if t["channels_n"] >= 10 and len(t["term"]) >= 4][:25]
    out.append("| term | channels_n | mentions |")
    out.append("|---|---:|---:|")
    for t in z:
        out.append(f"| `{t['term']}` | {t['channels_n']} | {t['post_mentions']} |")

    out.append("\n## Cadence (top 10 most active channels last 7d)")
    out.append("")
    cad = topics["cadence"]
    most_active = sorted(cad.items(), key=lambda kv: -kv[1].get("posts_last_7d", 0))[:10]
    out.append("| channel | last 7d | last 30d | per-day avg | peak hour UTC |")
    out.append("|---|---:|---:|---:|---:|")
    for ch, d in most_active:
        out.append(f"| `{ch}` | {d['posts_last_7d']} | {d['posts_last_30d']} | "
                   f"{d['posts_per_day_avg']} | {d['peak_hour_utc']} |")

    return "\n".join(out) + "\n"


def main() -> Path:
    md = render()
    out = REPORTS / "dashboard.md"
    out.write_text(md)
    print(f"[dashboard] wrote {out}")
    return out


if __name__ == "__main__":
    main()
