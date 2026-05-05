"""Topic & cadence analysis: posts/day per channel, weekly rhythm,
and rising/falling term burst detection.

A "burst" is a term whose share-of-corpus this week is significantly
higher than its 4-week trailing avg. We use a simple log-ratio with
Laplace smoothing — no sklearn dep.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import storage

LOG = logging.getLogger("ru_pulse.topics")

REPORTS = Path(__file__).parent / "reports"
REPORTS.mkdir(exist_ok=True)

WORD_RX = re.compile(r"[A-Za-zЀ-ӿ\d_\-]+", re.UNICODE)
LATIN_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
CYR_RX = re.compile(r"[Ѐ-ӿ]")

STOP = {
    # russian — pronouns, prepositions, conjunctions, particles
    "и","в","не","на","что","с","по","это","для","к","а","но","у","из","или",
    "так","же","то","как","за","от","о","со","до","при","об","ли","бы","ну",
    "вот","уже","его","ее","её","их","там","тут","тоже","этот","эта","эти",
    "тот","та","те","был","была","было","были","есть","когда","если","только",
    "еще","ещё","очень","чтобы","вы","мы","он","она","они","вас","нас","нам",
    "им","ему","ей","тем","будет","можно","нужно","надо","также","под","над","без","около","после","перед","через","про","сейчас","сегодня",
    "сразу","снова","всё","все","всех","всем","точно","именно","почти","лишь",
    "даже","потом","теперь","тогда","всегда","никогда","всё-таки","вообще",
    "может","сам","сама","сами","свой","своя","свои","своих","своим",
    "своей","своего","ваш","ваша","ваши","этих","этим","этой","этого",
    # russian — generic verbs/adverbs that appeared in Phase 2 zeitgeist top
    "пока","один","одна","одно","одни","просто","который","которые","которая",
    "которое","которых","которому","которой","которым","где","чем","раз","время",
    "этом","нет","том","тому","той","того","них","ними","нём","себе","себя",
    "собой","сделать","делать","делает","делают","сделал","сделала","сделали",
    "работает","работают","работать","работаем","работа","больше","меньше",
    "много","мало","новый","новая","новое","новые","раньше","лучше","хуже",
    "год","года","лет","день","дня","дней","неделя","недели","час","часа","часов",
    "минута","минуты","минут","например","да","далее","всего","часто","редко","иногда",
    "порой","вдруг","между","среди","возле",
    "против","ради","вместо","кроме","помимо","согласно",
    "несколько","многих","многим","многом","многой","многого","некоторые",
    "некоторых","некоторым","некоторой","некоторого","любой","любая","любое",
    "любые","любых","любому","своему","моих","мою","моей","моего",
    "наших","наши","нашим","нашей","вашим","вашу","вашей","вашего",
    "получится","получилось","получаем","получают","получает","получил",
    # russian — generic content noise (high freq, low information)
    "модели","модель","моделей","моделью","моделях",  # too generic in AI corpus
    # english — articles, prepositions, conjunctions, common verbs
    "the","a","an","and","or","but","of","in","on","to","for","with","is","are",
    "was","were","be","been","being","this","that","these","those","it","its",
    "as","at","by","from","if","then","than","so","such","no","not","do","does",
    "did","have","has","had","will","would","can","could","should","may","might",
    "we","our","you","your","they","them","their","i","me","my","he","him","his",
    "she","her","hers","there","here","what","when","how","why","which","who","whom",
    "more","most","also","one","two","three","new","just","like","very","much",
    "many","few","some","any","all","each","every","both","either","neither",
    "while","because","although","though","since","until","unless","whether",
    "into","onto","upon","over","under","above","below","through","during",
    # technical/url noise that pollutes "zeitgeist" without being a topic
    "https","http","www","com","org","ru","io","html","htm","txt","md","pdf",
}


def is_content(tok: str) -> bool:
    if tok in STOP:
        return False
    if tok.isdigit():
        return False
    if len(tok) < 3:
        return False
    return True


def tokens_of(text: str) -> list[str]:
    return [t for t in (w.lower() for w in WORD_RX.findall(text or "")) if is_content(t)]


def parse_iso(s: str) -> datetime:
    # storage stores ISO with +00:00 offset.
    return datetime.fromisoformat(s)


def iso_year_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def fetch_all() -> list[dict]:
    rows: list[dict] = []
    with storage.connect() as c:
        cur = c.execute("SELECT channel, posted_at, text FROM posts WHERE text != ''")
        for r in cur:
            rows.append({"channel": r["channel"], "posted_at": r["posted_at"], "text": r["text"]})
    return rows


def cadence(rows: list[dict]) -> dict:
    """Posts per day, weekday rhythm, hour-of-day spread."""
    by_channel = defaultdict(list)
    for r in rows:
        try:
            dt = parse_iso(r["posted_at"])
        except (ValueError, TypeError) as e:
            LOG.warning("bad posted_at=%r in channel=%s: %s",
                        r.get("posted_at"), r.get("channel"), e)
            continue
        by_channel[r["channel"]].append(dt)

    out = {}
    now = datetime.now(timezone.utc)
    for ch, dts in by_channel.items():
        if not dts:
            continue
        dts.sort()
        span_days = max(1, (dts[-1] - dts[0]).days)
        last_30_days = sum(1 for d in dts if (now - d).days <= 30)
        last_7_days = sum(1 for d in dts if (now - d).days <= 7)
        weekday = Counter(d.weekday() for d in dts)
        hour = Counter(d.hour for d in dts)
        out[ch] = {
            "n_posts": len(dts),
            "first_post": dts[0].isoformat(timespec="seconds"),
            "last_post": dts[-1].isoformat(timespec="seconds"),
            "span_days": span_days,
            "posts_per_day_avg": round(len(dts) / span_days, 3),
            "posts_last_7d": last_7_days,
            "posts_last_30d": last_30_days,
            "weekday_dist": {str(k): weekday[k] for k in sorted(weekday)},
            "peak_hour_utc": hour.most_common(1)[0][0] if hour else None,
        }
    return out


def burst_detection(rows: list[dict], top_k: int = 30) -> dict:
    """For each channel, compare the last 4 weeks with the prior 16 weeks.
    Return top rising / falling content terms by log-ratio."""
    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(days=28)
    cutoff_baseline = now - timedelta(days=140)

    recent: dict[str, Counter] = defaultdict(Counter)
    baseline: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        try:
            dt = parse_iso(r["posted_at"])
        except (ValueError, TypeError) as e:
            LOG.warning("bad posted_at=%r in channel=%s: %s",
                        r.get("posted_at"), r.get("channel"), e)
            continue
        toks = set(tokens_of(r["text"]))  # set: count by post-presence, not raw freq
        if dt >= cutoff_recent:
            recent[r["channel"]].update(toks)
        elif dt >= cutoff_baseline:
            baseline[r["channel"]].update(toks)

    out: dict[str, dict] = {}
    for ch in set(list(recent) + list(baseline)):
        rc = recent.get(ch, Counter())
        bc = baseline.get(ch, Counter())
        rsum = max(1, sum(rc.values()))
        bsum = max(1, sum(bc.values()))
        scores = []
        for term, n in rc.most_common(500):
            if n < 3:
                continue
            r_share = n / rsum
            b_share = (bc.get(term, 0) + 1) / (bsum + 1)
            lr = math.log(r_share / b_share)
            scores.append((term, round(lr, 3), n, bc.get(term, 0)))
        scores.sort(key=lambda x: x[1], reverse=True)
        out[ch] = {
            "rising": scores[:top_k],
            "falling": list(reversed(scores[-top_k:])),
            "recent_post_n": rsum,
            "baseline_post_n": bsum,
        }
    return out


def cross_channel_topic_overlap(rows: list[dict], top_k: int = 25) -> list[dict]:
    """What terms appear across many channels in the last 28 days? = the
    'shared zeitgeist'. Solo Lab can either join or counter-program."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=28)
    term_to_channels: defaultdict[str, set[str]] = defaultdict(set)
    term_to_count: Counter[str] = Counter()
    n_channels = set()
    for r in rows:
        try:
            dt = parse_iso(r["posted_at"])
        except (ValueError, TypeError) as e:
            LOG.warning("bad posted_at=%r in channel=%s: %s",
                        r.get("posted_at"), r.get("channel"), e)
            continue
        if dt < cutoff:
            continue
        n_channels.add(r["channel"])
        for tok in set(tokens_of(r["text"])):
            term_to_channels[tok].add(r["channel"])
            term_to_count[tok] += 1
    rows_out = []
    for term, ch_set in term_to_channels.items():
        if len(ch_set) < 3:
            continue
        rows_out.append({
            "term": term,
            "channels_n": len(ch_set),
            "post_mentions": term_to_count[term],
            "channels": sorted(ch_set),
        })
    rows_out.sort(key=lambda r: (r["channels_n"], r["post_mentions"]), reverse=True)
    return rows_out[:200]


def main() -> Path:
    rows = fetch_all()
    cad = cadence(rows)
    zeitgeist = cross_channel_topic_overlap(rows)
    out = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_posts": len(rows),
        "cadence": cad,
        "bursts_per_channel": burst_detection(rows),
        "cross_channel_zeitgeist_28d": zeitgeist,
    }
    path = REPORTS / "topics_report.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[topics] wrote {path}")
    print(f"[topics] cadence channels={len(cad)} zeitgeist_terms={len(zeitgeist)}")
    return path


if __name__ == "__main__":
    main()
