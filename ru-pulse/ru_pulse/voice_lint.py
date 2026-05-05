"""Voice Lint — score a RU post against the 50-channel RU Pulse voice fingerprints.

Usage:
    python -m ru_pulse.voice_lint --text "Текст поста..."
    python -m ru_pulse.voice_lint --file path/to/post.txt
    python -m ru_pulse.voice_lint --text "..." --json   # machine-readable only
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from .voice_fingerprint import (
    post_features,
    fingerprint_distance,
    VOICE_KEYS,
)

_REPORTS = Path(__file__).parent / "reports"
_FP_PATH = _REPORTS / "voice_fingerprint.json"

_CORPUS: dict | None = None


def _load_corpus() -> dict:
    global _CORPUS
    if _CORPUS is not None:
        return _CORPUS
    if not _FP_PATH.exists():
        raise FileNotFoundError(
            f"Fingerprint data not found at {_FP_PATH}. "
            "Run `python -m ru_pulse.voice_fingerprint` first."
        )
    _CORPUS = json.loads(_FP_PATH.read_text(encoding="utf-8"))
    return _CORPUS


@dataclass
class BucketMatch:
    bucket: str
    distance: float


@dataclass
class ChannelMatch:
    channel: str
    distance: float


@dataclass
class LintResult:
    raw_features: dict
    norm_features: dict
    nearest_buckets: list[BucketMatch]
    nearest_channels: list[ChannelMatch]
    hype_score: float          # 0..1 (caps weighted + bullet weighted)
    broadcast_score: float     # 0..1 (1 - first_person_per_100w_norm)
    listicle_hits: int         # raw integer count of listicle markers in post
    verdict: str

    def to_json(self) -> str:
        d = {
            "raw_features": self.raw_features,
            "norm_features": self.norm_features,
            "nearest_buckets": [asdict(b) for b in self.nearest_buckets],
            "nearest_channels": [asdict(c) for c in self.nearest_channels],
            "hype_score": self.hype_score,
            "broadcast_score": self.broadcast_score,
            "listicle_hits": self.listicle_hits,
            "verdict": self.verdict,
        }
        return json.dumps(d, ensure_ascii=False)


_VERDICT_MAP: dict[str, str] = {
    "ai_core":         "fits ai_core voice",
    "dev":             "leans dev_technical",
    "ml_aggregator":   "leans ml_aggregator",
    "indie_solo":      "leans indie_solo",
    "news_aggregator": "leans news_aggregator",
    "hype_listicle":   "leans hype_listicle",
    "prompt_specific": "leans prompt_specific",
}


def _normalize_single(raw: dict, corpus_raw: list[dict]) -> dict:
    """Min-max normalize raw feature dict against corpus raw channel vectors.

    The filter (`include all channels regardless of n_posts`) MUST match
    `voice_fingerprint.normalize_corpus` exactly — otherwise distance
    arithmetic at lint time uses a different range than the stored
    fingerprints, producing subtly wrong nearest-channel results.
    """
    norm: dict = {}
    for k in VOICE_KEYS:
        vals = [c.get(k, 0.0) for c in corpus_raw]
        if not vals:
            norm[k] = 0.0
            continue
        lo, hi = min(vals), max(vals)
        rng = hi - lo if hi > lo else 1.0
        val = raw.get(k, 0.0)
        # Clamp to corpus range so a single outlier post can't blow normalization.
        val = max(lo, min(hi, val))
        norm[k] = round((val - lo) / rng, 4)
    return norm


def _per_post_to_voice_raw(features: dict) -> dict:
    """Convert single-post post_features() output to voice-fingerprint scale."""
    n_words = max(1, features["words"])
    return {
        "exclam_per_100w":      round(features["exclam"] / n_words * 100, 3),
        "question_per_100w":    round(features["question"] / n_words * 100, 3),
        "emoji_per_post":       round(features["emoji_count"], 3),
        "caps_per_100w":        round(features["caps_words"] / n_words * 100, 3),
        "hashtag_per_post":     round(features["hashtag_count"], 3),
        "link_per_post":        round(features["url_count"], 3),
        "first_person_per_100w": round(features["first_person"] / n_words * 100, 3),
        "imperative_per_100w":  round(features["imperative_hits"] / n_words * 100, 3),
        "listicle_share":       round(min(features["listicle_hits"], 1), 3),
        "bullet_share":         round(features["has_bullets"], 3),
        "long_post_share":      round(features["long_post"], 3),
        "avg_sentence_len_words": round(features["sentence_len_words"], 3),
    }


def _hype_score(norm: dict) -> float:
    """0.0-1.0 — high caps density + heavy bullet use signals hype style."""
    caps = norm.get("caps_per_100w", 0.0)
    bullet = norm.get("bullet_share", 0.0)
    return round(min(1.0, (caps * 0.6 + bullet * 0.4)), 4)


def _broadcast_score(norm: dict) -> float:
    """0.0-1.0 — inverse of first-person density; 1.0 = fully impersonal broadcast."""
    fp = norm.get("first_person_per_100w", 0.0)
    return round(max(0.0, 1.0 - fp), 4)


def lint(text: str) -> LintResult:
    corpus = _load_corpus()
    corpus_raw: list[dict] = corpus["raw"]
    corpus_norm: list[dict] = corpus["normalized"]
    bucket_centroids: dict = corpus["bucket_centroids"]

    pf = post_features(text)
    raw_voice = _per_post_to_voice_raw(pf)
    norm_voice = _normalize_single(raw_voice, corpus_raw)

    bucket_dists = []
    for bucket, meta in bucket_centroids.items():
        centroid = meta["centroid"]
        d = fingerprint_distance(norm_voice, centroid, VOICE_KEYS)
        bucket_dists.append(BucketMatch(bucket=bucket, distance=round(d, 4)))
    bucket_dists.sort(key=lambda x: x.distance)
    nearest_buckets = bucket_dists[:3]

    channel_dists = []
    for ch in corpus_norm:
        if ch.get("n_posts", 0) == 0:
            continue
        d = fingerprint_distance(norm_voice, ch, VOICE_KEYS)
        channel_dists.append(ChannelMatch(channel=ch["name"], distance=round(d, 4)))
    channel_dists.sort(key=lambda x: x.distance)
    nearest_channels = channel_dists[:5]

    hs = _hype_score(norm_voice)
    bs = _broadcast_score(norm_voice)
    listicle_hits = int(pf["listicle_hits"])

    if nearest_buckets:
        top_bucket = nearest_buckets[0].bucket
        verdict = _VERDICT_MAP.get(top_bucket, f"closest to {top_bucket}")
    else:
        verdict = "no buckets in corpus — run voice_fingerprint first"

    return LintResult(
        raw_features=raw_voice,
        norm_features=norm_voice,
        nearest_buckets=nearest_buckets,
        nearest_channels=nearest_channels,
        hype_score=hs,
        broadcast_score=bs,
        listicle_hits=listicle_hits,
        verdict=verdict,
    )


def _render_markdown(result: LintResult) -> str:
    lines: list[str] = []

    lines.append("## Voice Lint Report\n")
    lines.append(f"**Verdict:** {result.verdict}")
    lines.append(
        f"**Scores:** hype={result.hype_score:.3f}  "
        f"broadcast={result.broadcast_score:.3f}  "
        f"listicle_hits={result.listicle_hits}\n"
    )

    lines.append("### Nearest buckets")
    lines.append("| bucket | distance |")
    lines.append("|--------|----------|")
    for b in result.nearest_buckets:
        lines.append(f"| {b.bucket} | {b.distance:.4f} |")

    lines.append("\n### Nearest channels")
    lines.append("| channel | distance |")
    lines.append("|---------|----------|")
    for c in result.nearest_channels:
        lines.append(f"| {c.channel} | {c.distance:.4f} |")

    lines.append("\n### Post voice features (raw / normalized)")
    lines.append("| feature | raw | norm |")
    lines.append("|---------|-----|------|")
    for k in VOICE_KEYS:
        r = result.raw_features.get(k, 0.0)
        n = result.norm_features.get(k, 0.0)
        lines.append(f"| {k} | {r:.3f} | {n:.4f} |")

    return "\n".join(lines)


def _cli(argv: list[str]) -> None:
    args = argv[1:]
    text: str = ""
    json_only = False

    i = 0
    while i < len(args):
        if args[i] == "--text" and i + 1 < len(args):
            text = args[i + 1]
            i += 2
        elif args[i] == "--file" and i + 1 < len(args):
            p = Path(args[i + 1])
            if not p.exists():
                print(f"error: file not found: {p}", file=sys.stderr)
                sys.exit(1)
            text = p.read_text(encoding="utf-8")
            i += 2
        elif args[i] == "--json":
            json_only = True
            i += 1
        elif args[i] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"error: unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    if not text.strip():
        print("error: provide --text or --file with non-empty content", file=sys.stderr)
        sys.exit(1)

    try:
        result = lint(text)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if json_only:
        print(result.to_json())
    else:
        print(_render_markdown(result))
        print("\n---")
        print(result.to_json())


if __name__ == "__main__":
    _cli(sys.argv)
