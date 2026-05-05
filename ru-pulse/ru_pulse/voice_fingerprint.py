"""Voice fingerprint per channel — distinctive style metrics that go
beyond raw vocab. Used to position Solo Lab's voice in the landscape.

Metrics computed per channel (averaged across all posts):
  - sentence_len_words
  - exclam_per_100w   -- exclamation density (hype proxy)
  - question_per_100w
  - emoji_per_post
  - caps_per_100w     -- ALL-CAPS WORD density (loud proxy)
  - hashtag_per_post
  - link_per_post     -- citation/receipt proxy
  - first_person_share -- я/мы/наш/мой counts (personal voice)
  - imperative_share  -- glagol -ите/-ите/-й endings (broadcast voice)
  - listicle_score    -- presence of "ТОП", "5 нейросетей", numbered lists
  - bullet_share      -- posts using bullet/dash markers
  - long_post_share   -- share of posts >800 chars (long-form indicator)

Output: reports/voice_fingerprint.json — per-channel feature vector +
         per-bucket centroid + outlier flag.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import storage

REPORTS = Path(__file__).parent / "reports"
REPORTS.mkdir(exist_ok=True)

WORD_RX = re.compile(r"[A-Za-zЀ-ӿ\d_\-]+", re.UNICODE)
EMOJI_RX = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U00002600-\U000026FF\U00002700-\U000027BF⌀-⏿]+",
    flags=re.UNICODE,
)
URL_RX = re.compile(r"https?://\S+")
HASHTAG_RX = re.compile(r"#\w+", re.UNICODE)
SENT_SPLIT = re.compile(r"[.!?]+|\n{2,}")

FIRST_PERSON = {"я", "меня", "мне", "мной", "мы", "нас", "нам", "нами",
                "мой", "моя", "моё", "мои", "наш", "наша", "наше", "наши"}
IMPERATIVE_RX = re.compile(r"\b\w+(й|йте|ите|и)\b", re.UNICODE)
LISTICLE_RX = re.compile(
    r"\b(топ|top)[\s-]?\d+|\b\d+\s+(нейросет|инструмент|сервис|способ|совет)|"
    r"\b\d+\s+(things|tools|tips|ways)|^[1-9][\.\)]\s",
    re.IGNORECASE | re.MULTILINE,
)
BULLET_RX = re.compile(r"^\s*[•\-—–\*]\s|^\s*[1-9][\.\)]\s", re.MULTILINE)


def post_features(text: str) -> dict:
    text = text or ""
    words = WORD_RX.findall(text)
    n_words = max(1, len(words))
    sentences = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    n_sent = max(1, len(sentences))
    fp = sum(1 for w in (w.lower() for w in words) if w in FIRST_PERSON)
    imp = len([m for m in IMPERATIVE_RX.findall(text) if len(m) >= 2])
    return {
        "chars": len(text),
        "words": n_words,
        "sentences": n_sent,
        "sentence_len_words": n_words / n_sent,
        "emoji_count": len(EMOJI_RX.findall(text)),
        "url_count": len(URL_RX.findall(text)),
        "hashtag_count": len(HASHTAG_RX.findall(text)),
        "exclam": text.count("!"),
        "question": text.count("?"),
        "caps_words": sum(1 for w in text.split() if w.isupper() and len(w) > 1),
        "first_person": fp,
        "imperative_hits": imp,
        "listicle_hits": len(LISTICLE_RX.findall(text)),
        "has_bullets": 1 if BULLET_RX.search(text) else 0,
        "long_post": 1 if len(text) > 800 else 0,
    }


def per_channel(name: str, posts: list[str]) -> dict:
    if not posts:
        return {"name": name, "n_posts": 0}
    feats = [post_features(p) for p in posts]
    n = len(feats)
    sum_words = sum(f["words"] for f in feats)

    def avg_per_post(key):
        return statistics.mean(f[key] for f in feats) if feats else 0

    def per_100w(key):
        return (sum(f[key] for f in feats) / max(1, sum_words)) * 100

    fp = {
        "name": name,
        "n_posts": n,
        "avg_chars": round(statistics.mean(f["chars"] for f in feats), 1),
        "avg_words": round(statistics.mean(f["words"] for f in feats), 1),
        "avg_sentence_len_words": round(statistics.mean(f["sentence_len_words"] for f in feats), 2),
        "median_chars": round(statistics.median(f["chars"] for f in feats), 1),
        "exclam_per_100w": round(per_100w("exclam"), 3),
        "question_per_100w": round(per_100w("question"), 3),
        "emoji_per_post": round(avg_per_post("emoji_count"), 3),
        "caps_per_100w": round(per_100w("caps_words"), 3),
        "hashtag_per_post": round(avg_per_post("hashtag_count"), 3),
        "link_per_post": round(avg_per_post("url_count"), 3),
        "first_person_per_100w": round(per_100w("first_person"), 3),
        "imperative_per_100w": round(per_100w("imperative_hits"), 3),
        "listicle_share": round(sum(1 for f in feats if f["listicle_hits"] > 0) / n, 4),
        "bullet_share": round(sum(f["has_bullets"] for f in feats) / n, 4),
        "long_post_share": round(sum(f["long_post"] for f in feats) / n, 4),
    }
    return fp


def fingerprint_distance(a: dict, b: dict, keys: list[str]) -> float:
    """Normalized euclidean distance over selected keys (ignoring magnitude
    by min-max within full corpus). Caller normalizes before passing."""
    d = 0.0
    for k in keys:
        d += (a.get(k, 0) - b.get(k, 0)) ** 2
    return d ** 0.5


def normalize_corpus(channels: list[dict], keys: list[str]) -> list[dict]:
    out = [dict(c) for c in channels]
    for k in keys:
        vals = [c.get(k, 0) for c in channels if c.get("n_posts", 0) > 0]
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        rng = hi - lo if hi > lo else 1.0
        for c in out:
            c[k] = round(((c.get(k, 0) - lo) / rng), 4) if c.get("n_posts", 0) > 0 else 0
    return out


VOICE_KEYS = [
    "exclam_per_100w", "question_per_100w", "emoji_per_post", "caps_per_100w",
    "hashtag_per_post", "link_per_post", "first_person_per_100w",
    "imperative_per_100w", "listicle_share", "bullet_share", "long_post_share",
    "avg_sentence_len_words",
]


def main() -> Path:
    fps = []
    channel_meta: dict[str, str] = {}
    with storage.connect() as c:
        chs = c.execute("SELECT name, bucket FROM channels").fetchall()
        for r in chs:
            channel_meta[r["name"]] = r["bucket"]
            posts = [
                row["text"] for row in c.execute(
                    "SELECT text FROM posts WHERE channel=? AND text != ''",
                    (r["name"],),
                ).fetchall()
            ]
            fps.append(per_channel(r["name"], posts))

    fps_norm = normalize_corpus(fps, VOICE_KEYS)
    by_bucket = defaultdict(list)
    for fp in fps_norm:
        b = channel_meta.get(fp["name"])
        if b and fp.get("n_posts", 0) > 0:
            by_bucket[b].append(fp)

    bucket_centroids = {}
    for bucket, items in by_bucket.items():
        centroid = {}
        for k in VOICE_KEYS:
            centroid[k] = round(statistics.mean(it[k] for it in items), 4)
        bucket_centroids[bucket] = {
            "n_channels": len(items),
            "centroid": centroid,
        }

    # Per channel: distance to its own bucket centroid; flag outliers.
    for fp in fps_norm:
        b = channel_meta.get(fp["name"])
        if not b or fp.get("n_posts", 0) == 0:
            continue
        # cast: bucket_centroids[b]["centroid"] is a dict at runtime; mypy
        # types it as `object` because bucket_centroids[b] is dict[str, object].
        cent = bucket_centroids[b]["centroid"]
        assert isinstance(cent, dict)
        d = fingerprint_distance(fp, cent, VOICE_KEYS)
        fp["dist_to_bucket_centroid"] = round(d, 4)

    # Build a separate "raw" view (un-normalized) for human reading.
    out = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "voice_keys": VOICE_KEYS,
        "raw": fps,
        "normalized": fps_norm,
        "bucket_centroids": bucket_centroids,
    }
    path = REPORTS / "voice_fingerprint.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[voice] wrote {path}")
    print(f"[voice] channels={len(fps)} buckets={list(bucket_centroids)}")
    return path


if __name__ == "__main__":
    main()
