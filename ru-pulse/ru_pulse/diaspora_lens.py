"""Sub-corpus analyzer — focus the lexicon + voice + topics analysis on a
specific bucket subset (e.g. diaspora_relocant or founders_diary).

Why: bucket-aggregate stats in the master report mix all 12 buckets
together. To find what makes the diaspora_relocant niche distinctive, we
need stats computed ONLY over those channels, plus a comparative view
against the rest of the corpus.

Output: `reports/lens_<bucket>.md` and `reports/lens_<bucket>.json` with:
- Top tokens unique to this bucket (high lift vs rest of corpus)
- Voice fingerprint diff: how this bucket differs from corpus mean
- Top bigrams that DON'T appear elsewhere
- Cross-bucket Jaccard rank: closest neighbours
- Cadence signature
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import storage
from .analyze import (tokenize, is_cyrillic, is_latin, is_stopword,
                      n_grams, jaccard)

LOG = logging.getLogger("ru_pulse.lens")
REPORTS = Path(__file__).parent / "reports"
_BUCKET_NAME_RX = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _channels_in_bucket(bucket: str) -> list[str]:
    """Return channel names belonging to `bucket`, sorted alphabetically."""
    with storage.connect() as c:
        rows = c.execute(
            "SELECT name FROM channels WHERE bucket=? ORDER BY name", (bucket,)
        ).fetchall()
    return [r["name"] for r in rows]


def _all_channels_grouped() -> dict[str, list[str]]:
    """Group every known channel by its bucket. Returns {bucket: [channels]}."""
    out: dict[str, list[str]] = defaultdict(list)
    with storage.connect() as c:
        rows = c.execute("SELECT name, bucket FROM channels ORDER BY name").fetchall()
    for r in rows:
        out[r["bucket"]].append(r["name"])
    return out


def _posts_for_channels(channels: list[str]) -> list[tuple[str, str]]:
    """Pull (posted_at, text) for every non-empty post in any of `channels`."""
    if not channels:
        return []
    with storage.connect() as c:
        placeholders = ",".join(["?"] * len(channels))
        rows = c.execute(
            f"SELECT posted_at, text FROM posts "
            f"WHERE channel IN ({placeholders}) AND text != ''",
            channels,
        ).fetchall()
    return [(r["posted_at"], r["text"]) for r in rows]


def _term_freq(posts: list[tuple[str, str]]) -> Counter[str]:
    """Token-frequency counter from posts. Keeps content tokens only."""
    c: Counter[str] = Counter()
    for _, text in posts:
        for tok in tokenize(text):
            if is_stopword(tok) or len(tok) < 3 or tok.isdigit():
                continue
            if not (is_cyrillic(tok) or is_latin(tok)):
                continue
            c[tok] += 1
    return c


def _bigram_freq(posts: list[tuple[str, str]]) -> Counter[tuple[str, ...]]:
    """Bigram-frequency counter from post bodies. Strips stopwords + digits.
    Note: returns Counter[tuple[str, ...]] to match analyze.n_grams signature
    (variable-arity tuple) — at this call site we only ever pass n=2."""
    c: Counter[tuple[str, ...]] = Counter()
    for _, text in posts:
        toks = [t for t in tokenize(text)
                if not is_stopword(t) and len(t) >= 2 and not t.isdigit()]
        c.update(n_grams(toks, 2))
    return c


def _lift_table(bucket_freq: Counter, rest_freq: Counter,
                bucket_total: int, rest_total: int,
                top_k: int = 50, min_count: int = 5) -> list[dict]:
    """Pointwise mutual-information style lift: term's share in bucket
    vs in rest, log-ratio (Laplace smoothed).
    Returns top_k terms by lift descending."""
    if bucket_total == 0:
        return []
    out = []
    for term, n_b in bucket_freq.most_common():
        if n_b < min_count:
            continue
        n_r = rest_freq.get(term, 0)
        share_b = (n_b + 1) / (bucket_total + 1)
        share_r = (n_r + 1) / (rest_total + 1)
        lift = math.log(share_b / share_r)
        out.append({
            "term": term, "lift": round(lift, 3),
            "count_bucket": n_b, "count_rest": n_r,
        })
    out.sort(key=lambda x: x["lift"], reverse=True)
    return out[:top_k]


def _bucket_voice_centroid(bucket_channels: list[str]) -> dict:
    """Read `reports/voice_fingerprint.json` and compute the centroid for
    the given bucket. Returns empty dict if the fingerprint file is missing
    or no channels in the bucket have voice data."""
    fp_path = REPORTS / "voice_fingerprint.json"
    if not fp_path.exists():
        return {}
    fp = json.loads(fp_path.read_text(encoding="utf-8"))
    voice_keys = fp.get("voice_keys", [])
    members = [c for c in fp.get("normalized", []) if c.get("name") in bucket_channels]
    if not members:
        return {}
    centroid = {}
    for k in voice_keys:
        vals = [c.get(k, 0.0) for c in members]
        centroid[k] = round(sum(vals) / len(vals), 4) if vals else 0.0
    return centroid


def _voice_delta_vs_corpus(bucket_centroid: dict, voice_keys: list[str]) -> dict:
    """For each voice axis: how does this bucket deviate from corpus-wide
    mean? Returns {axis: delta} where positive = bucket scores higher."""
    fp_path = REPORTS / "voice_fingerprint.json"
    if not fp_path.exists() or not bucket_centroid:
        return {}
    fp = json.loads(fp_path.read_text(encoding="utf-8"))
    all_norm = [c for c in fp.get("normalized", []) if c.get("n_posts", 0) > 0]
    if not all_norm:
        return {}
    delta = {}
    for k in voice_keys:
        corpus_mean = sum(c.get(k, 0.0) for c in all_norm) / len(all_norm)
        delta[k] = round(bucket_centroid.get(k, 0.0) - corpus_mean, 4)
    return delta


def _cross_bucket_jaccard(this_bucket_terms: set[str],
                          all_buckets: dict[str, list[str]],
                          this_bucket_name: str) -> list[dict]:
    """Compare this bucket's vocab vs each other bucket's pooled vocab."""
    out = []
    for bname, channels in all_buckets.items():
        if bname == this_bucket_name:
            continue
        posts = _posts_for_channels(channels)
        if not posts:
            continue
        other = set(_term_freq(posts).keys())
        # Sort before slicing — set ordering is non-deterministic across runs.
        a = set(sorted(this_bucket_terms)[:500])
        b = set(sorted(other)[:500])
        out.append({
            "other_bucket": bname,
            "n_channels": len(channels),
            "jaccard": round(jaccard(a, b), 4),
        })
    out.sort(key=lambda r: r["jaccard"], reverse=True)  # type: ignore[arg-type,return-value]
    return out


def lens(bucket: str, top_k: int = 50) -> dict:
    """Run the full sub-corpus lens for `bucket`."""
    channels = _channels_in_bucket(bucket)
    if not channels:
        raise ValueError(f"bucket {bucket!r} has no channels in DB")
    all_buckets = _all_channels_grouped()
    rest_channels = [c for b, lst in all_buckets.items() if b != bucket
                     for c in lst]

    bucket_posts = _posts_for_channels(channels)
    rest_posts = _posts_for_channels(rest_channels)

    bucket_freq = _term_freq(bucket_posts)
    rest_freq = _term_freq(rest_posts)
    bucket_total = sum(bucket_freq.values())
    rest_total = sum(rest_freq.values())

    bucket_bigrams = _bigram_freq(bucket_posts)
    rest_bigrams = _bigram_freq(rest_posts)

    # Bigrams unique-ish to this bucket
    unique_bigrams = []
    for bg, c in bucket_bigrams.most_common(top_k * 4):
        rest_c = rest_bigrams.get(bg, 0)
        if c >= 5 and (c / max(rest_c + 1, 1)) >= 3:
            unique_bigrams.append({
                "bigram": " ".join(bg),
                "count_bucket": c, "count_rest": rest_c,
            })
        if len(unique_bigrams) >= top_k:
            break

    voice_keys = ["exclam_per_100w", "question_per_100w", "emoji_per_post",
                  "caps_per_100w", "hashtag_per_post", "link_per_post",
                  "first_person_per_100w", "imperative_per_100w",
                  "listicle_share", "bullet_share", "long_post_share",
                  "avg_sentence_len_words"]
    centroid = _bucket_voice_centroid(channels)
    delta = _voice_delta_vs_corpus(centroid, voice_keys)

    cross = _cross_bucket_jaccard(set(bucket_freq.keys()), all_buckets, bucket)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bucket": bucket,
        "n_channels": len(channels),
        "n_posts": len(bucket_posts),
        "n_tokens": bucket_total,
        "channels": channels,
        "top_lift_terms": _lift_table(bucket_freq, rest_freq,
                                       bucket_total, rest_total, top_k),
        "unique_bigrams": unique_bigrams,
        "voice_centroid": centroid,
        "voice_delta_vs_corpus_mean": delta,
        "cross_bucket_jaccard": cross,
    }


def render_md(report: dict) -> str:
    """Render a focused human-readable markdown summary."""
    out = []
    out.append(f"# Lens — `{report['bucket']}`\n")
    out.append(f"_{report['n_channels']} channels · {report['n_posts']:,} posts · "
               f"{report['n_tokens']:,} content tokens · "
               f"generated {report['generated_at']}_\n")

    out.append("## Top distinctive terms (lift vs rest of corpus)\n")
    out.append("| term | lift | bucket | rest |")
    out.append("|------|-----:|-------:|-----:|")
    for r in report["top_lift_terms"][:25]:
        out.append(f"| `{r['term']}` | {r['lift']} | "
                   f"{r['count_bucket']} | {r['count_rest']} |")

    out.append("\n## Distinctive bigrams (≥3× over rest)\n")
    if report["unique_bigrams"]:
        out.append("| bigram | bucket | rest |")
        out.append("|--------|------:|-----:|")
        for r in report["unique_bigrams"][:20]:
            out.append(f"| `{r['bigram']}` | {r['count_bucket']} | {r['count_rest']} |")
    else:
        out.append("_(no bigrams meeting the 3× threshold)_")

    out.append("\n## Voice delta vs corpus mean")
    out.append("Positive = this bucket scores higher than the corpus average.")
    out.append("")
    if report["voice_delta_vs_corpus_mean"]:
        out.append("| axis | delta |")
        out.append("|------|------:|")
        sorted_delta = sorted(
            report["voice_delta_vs_corpus_mean"].items(),
            key=lambda kv: abs(kv[1]), reverse=True,
        )
        for axis, d in sorted_delta:
            sign = "+" if d > 0 else ""
            out.append(f"| {axis} | {sign}{d} |")
    else:
        out.append("_(no voice fingerprint data — run voice_fingerprint.py first)_")

    out.append("\n## Closest other buckets (vocab Jaccard)\n")
    out.append("| bucket | n_channels | jaccard |")
    out.append("|--------|-----------:|--------:|")
    for r in report["cross_bucket_jaccard"]:
        out.append(f"| `{r['other_bucket']}` | {r['n_channels']} | {r['jaccard']} |")

    out.append("\n## Channels in bucket\n")
    out.append(", ".join(f"`{c}`" for c in report["channels"]))
    return "\n".join(out) + "\n"


def _bucket_arg(value: str) -> str:
    if not _BUCKET_NAME_RX.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"bucket name {value!r} must match {_BUCKET_NAME_RX.pattern}"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True, type=_bucket_arg,
                    help="bucket name (e.g. diaspora_relocant, founders_diary)")
    ap.add_argument("--top-k", type=int, default=50)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    try:
        report = lens(args.bucket, top_k=args.top_k)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    REPORTS.mkdir(exist_ok=True)
    json_out = REPORTS / f"lens_{args.bucket}.json"
    md_out = REPORTS / f"lens_{args.bucket}.md"
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    md_out.write_text(render_md(report), encoding="utf-8")
    LOG.info("wrote %s + %s · bucket=%s channels=%d posts=%d tokens=%d",
             json_out, md_out, args.bucket, report["n_channels"],
             report["n_posts"], report["n_tokens"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
