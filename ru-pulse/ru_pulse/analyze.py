"""Deterministic stats over the RU Pulse corpus. Pure stdlib + sqlite.

Outputs a single JSON report with:
  - global counters (posts, channels, tokens)
  - per-bucket aggregates
  - per-channel: top words, top bigrams, loanword share, code-switching rate
  - cross-channel: pairwise word-set Jaccard

No LLM calls — these numbers are receipts. Subagents will then INTERPRET
this report and turn it into prose / threads / strategic synthesis.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import storage

REPORTS = Path(__file__).parent / "reports"
REPORTS.mkdir(exist_ok=True)

# Russian + Latin word tokenizer.
TOKEN_RX = re.compile(r"[A-Za-zЀ-ӿ\d_\-]+", re.UNICODE)
LATIN_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
CYR_RX = re.compile(r"[Ѐ-ӿ]")
EMOJI_RX = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U00002600-\U000026FF\U00002700-\U000027BF⌀-⏿]+",
    flags=re.UNICODE,
)
URL_RX = re.compile(r"https?://\S+")
HASHTAG_RX = re.compile(r"#[A-Za-z0-9_Ѐ-ӿ]+")

# Cyrillic noise — single-letter prepositions/conjunctions/particles.
RU_STOPWORDS = {
    "и", "в", "не", "на", "что", "с", "по", "это", "для", "к", "а", "но",
    "у", "из", "или", "так", "же", "то", "как", "за", "от", "о", "со",
    "до", "при", "об", "ли", "бы", "ну", "вот", "уже", "его", "ее", "её",
    "их", "там", "тут", "тоже", "этот", "эта", "эти", "тот", "та", "те",
    "был", "была", "было", "были", "есть", "будет", "когда", "если",
    "только", "еще", "ещё", "очень", "чтобы", "вы", "мы", "он", "она",
    "они", "вас", "нас", "нам", "им", "ему", "ей", "тем",
    "будто", "чем", "лет", "год",
    "раз", "также", "хотя", "более", "менее", "куда", "где", "под", "над", "без", "около", "после", "перед", "через", "про",
    "точно", "просто", "много", "сам", "сама", "сами", "свой", "своя",
    "может", "можно", "нужно", "надо", "будут",
    "среди", "между", "из-за", "из-под", "вместо", "ради",
    "т", "д", "т.е", "т.д", "т.к", "тк", "тд", "вообще", "ведь",
    "тогда", "потом", "сейчас", "теперь", "иногда", "почему",
    "сегодня", "вчера", "завтра", "всё", "все", "всех", "всем", "конечно", "наверное", "именно", "почти", "лишь", "даже",
    "вдруг", "сразу", "снова", "вновь", "обычно", "часто",
    "редко", "всегда", "никогда", "всё-таки",
}
EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "to", "for",
    "with", "is", "are", "was", "were", "be", "been", "being", "this",
    "that", "these", "those", "it", "its", "as", "at", "by", "from", "if",
    "then", "than", "so", "such", "no", "not", "do", "does", "did", "have",
    "has", "had", "will", "would", "can", "could", "should", "may", "might",
    "we", "our", "you", "your", "they", "them", "their", "i", "me", "my",
    "he", "him", "his", "she", "her", "hers",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RX.findall(text or "")]


def is_latin(tok: str) -> bool:
    return bool(LATIN_RX.match(tok))


def is_cyrillic(tok: str) -> bool:
    return bool(CYR_RX.search(tok)) and not LATIN_RX.match(tok)


def is_stopword(tok: str) -> bool:
    return tok in RU_STOPWORDS or tok in EN_STOPWORDS


def post_metrics(text: str) -> dict:
    """Lightweight per-post metrics that don't require global counts."""
    tokens = tokenize(text)
    total = len(tokens)
    cyr = sum(1 for t in tokens if is_cyrillic(t))
    lat = sum(1 for t in tokens if is_latin(t))
    digits = sum(1 for t in tokens if t.isdigit())
    chars = len(text or "")
    sentences = max(1, sum(1 for c in (text or "") if c in ".!?\n"))
    return {
        "tokens": total,
        "tokens_cyr": cyr,
        "tokens_lat": lat,
        "tokens_digits": digits,
        "chars": chars,
        "sentences": sentences,
        "emoji_count": len(EMOJI_RX.findall(text or "")),
        "url_count": len(URL_RX.findall(text or "")),
        "hashtag_count": len(HASHTAG_RX.findall(text or "")),
        "exclam_count": (text or "").count("!"),
        "question_count": (text or "").count("?"),
        "caps_words": sum(1 for w in (text or "").split() if w.isupper() and len(w) > 1),
        "loanword_share": (lat / cyr) if cyr else 0.0,
    }


def n_grams(tokens: list[str], n: int) -> Counter[tuple[str, ...]]:
    return Counter(zip(*[tokens[i:] for i in range(n)], strict=False))


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def fetch_corpus() -> dict[str, dict]:
    """Returns {channel: {"bucket": ..., "posts": [(posted_at, text)]}}."""
    out: dict[str, dict] = {}
    with storage.connect() as c:
        chs = c.execute("SELECT name, bucket FROM channels").fetchall()
        for r in chs:
            posts = c.execute(
                "SELECT posted_at, text FROM posts "
                "WHERE channel=? AND text != '' "
                "ORDER BY posted_at",
                (r["name"],),
            ).fetchall()
            out[r["name"]] = {
                "bucket": r["bucket"],
                "posts": [(p["posted_at"], p["text"]) for p in posts],
            }
    return out


def per_channel_stats(name: str, posts: list[tuple[str, str]], top_k: int = 50) -> dict:
    all_tokens: list[str] = []
    cyr_tokens: list[str] = []
    lat_tokens: list[str] = []
    bigrams: Counter = Counter()
    metrics_acc: Counter[str] = Counter()
    n_posts = len(posts)
    if not posts:
        return {"name": name, "n_posts": 0}

    for _, text in posts:
        toks = tokenize(text)
        all_tokens.extend(toks)
        for t in toks:
            if is_cyrillic(t):
                cyr_tokens.append(t)
            elif is_latin(t):
                lat_tokens.append(t)
        # bigrams over content tokens (drop stopwords, length>=2)
        content = [t for t in toks if not is_stopword(t) and len(t) >= 2]
        bigrams.update(n_grams(content, 2))
        m = post_metrics(text)
        for k, v in m.items():
            metrics_acc[k] += v

    cyr_freq = Counter(t for t in cyr_tokens if not is_stopword(t) and len(t) >= 3)
    lat_freq = Counter(t for t in lat_tokens if not is_stopword(t) and len(t) >= 2)

    avg = {
        "post_chars": metrics_acc["chars"] / n_posts,
        "post_tokens": metrics_acc["tokens"] / n_posts,
        "post_sentences": metrics_acc["sentences"] / n_posts,
        "post_emoji": metrics_acc["emoji_count"] / n_posts,
        "post_url": metrics_acc["url_count"] / n_posts,
        "post_hashtag": metrics_acc["hashtag_count"] / n_posts,
        "post_exclam": metrics_acc["exclam_count"] / n_posts,
        "post_question": metrics_acc["question_count"] / n_posts,
        "post_caps_words": metrics_acc["caps_words"] / n_posts,
    }

    # Loanword share = latin / (cyrillic + latin) over CONTENT tokens only.
    cyr_content_n = sum(1 for t in cyr_tokens if not is_stopword(t) and len(t) >= 3)
    lat_content_n = sum(1 for t in lat_tokens if not is_stopword(t) and len(t) >= 2)
    loan_share = lat_content_n / max(1, cyr_content_n + lat_content_n)

    # Code-switching rate = posts that contain both RU and EN content tokens.
    mixed = 0
    for _, text in posts:
        toks = tokenize(text)
        has_ru = any(is_cyrillic(t) and not is_stopword(t) and len(t) >= 3 for t in toks)
        has_en = any(is_latin(t) and not is_stopword(t) and len(t) >= 2 for t in toks)
        if has_ru and has_en:
            mixed += 1
    code_switching = mixed / n_posts

    return {
        "name": name,
        "n_posts": n_posts,
        "n_tokens": len(all_tokens),
        "n_cyr": len(cyr_tokens),
        "n_lat": len(lat_tokens),
        "loanword_share": round(loan_share, 4),
        "code_switching_rate": round(code_switching, 4),
        "avg_per_post": {k: round(v, 3) for k, v in avg.items()},
        "top_cyr": cyr_freq.most_common(top_k),
        "top_lat": lat_freq.most_common(top_k),
        "top_bigrams": [(" ".join(bg), c) for bg, c in bigrams.most_common(top_k)],
    }


def per_bucket_aggregate(channel_stats: list[dict],
                         channels_meta: dict[str, str]) -> dict[str, dict]:
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for cs in channel_stats:
        b = channels_meta.get(cs["name"])
        if b is None or cs.get("n_posts", 0) == 0:
            continue
        by_bucket[b].append(cs)
    out = {}
    for bucket, items in by_bucket.items():
        n_posts = sum(x["n_posts"] for x in items)
        loan_share = sum(x["loanword_share"] * x["n_posts"] for x in items) / max(1, n_posts)
        code_sw = sum(x["code_switching_rate"] * x["n_posts"] for x in items) / max(1, n_posts)

        # Pool top terms across bucket (weighted).
        pool_cyr: Counter[str] = Counter()
        pool_lat: Counter[str] = Counter()
        pool_bg: Counter[str] = Counter()
        for x in items:
            for t, c in x["top_cyr"]:
                pool_cyr[t] += c
            for t, c in x["top_lat"]:
                pool_lat[t] += c
            for t, c in x["top_bigrams"]:
                pool_bg[t] += c

        out[bucket] = {
            "channels": [x["name"] for x in items],
            "n_channels": len(items),
            "n_posts": n_posts,
            "loanword_share": round(loan_share, 4),
            "code_switching_rate": round(code_sw, 4),
            "top_cyr": pool_cyr.most_common(40),
            "top_lat": pool_lat.most_common(40),
            "top_bigrams": pool_bg.most_common(40),
        }
    return out


def cross_channel_similarity(channel_stats: list[dict], top_k: int = 200) -> list[dict]:
    """Pairwise Jaccard over each channel's top-k content vocab.
    Cheap proxy for 'who sounds like whom'.
    """
    vocabs: dict[str, set[str]] = {}
    for cs in channel_stats:
        if cs.get("n_posts", 0) < 5:
            continue
        words = [t for t, _ in cs["top_cyr"][:top_k]]
        words += [t for t, _ in cs["top_lat"][:top_k // 2]]
        vocabs[cs["name"]] = set(words)
    pairs = []
    names = sorted(vocabs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            j = jaccard(vocabs[a], vocabs[b])
            pairs.append({"a": a, "b": b, "jaccard": round(j, 4)})
    pairs.sort(key=lambda p: p["jaccard"], reverse=True)  # type: ignore[arg-type,return-value]
    return pairs


def main() -> Path:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    corpus = fetch_corpus()
    channels_meta = {n: data["bucket"] for n, data in corpus.items()}

    channel_stats = []
    for name, data in corpus.items():
        cs = per_channel_stats(name, data["posts"])
        channel_stats.append(cs)

    bucket_stats = per_bucket_aggregate(channel_stats, channels_meta)
    sim = cross_channel_similarity(channel_stats)

    n_total = sum(x["n_posts"] for x in channel_stats)
    n_tokens = sum(x.get("n_tokens", 0) for x in channel_stats)

    report = {
        "schema_version": 1,
        "generated_at": started,
        "corpus": {
            "channels": len(channel_stats),
            "posts": n_total,
            "tokens": n_tokens,
        },
        "per_channel": channel_stats,
        "per_bucket": bucket_stats,
        "cross_channel_similarity_top": sim[:80],
        "cross_channel_similarity_bottom": sim[-30:],
    }
    out = REPORTS / "lexicon_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[analyze] wrote {out}")
    print(f"[analyze] channels={len(channel_stats)} posts={n_total} tokens={n_tokens}")
    print(f"[analyze] buckets={list(bucket_stats)}")
    return out


if __name__ == "__main__":
    main()
