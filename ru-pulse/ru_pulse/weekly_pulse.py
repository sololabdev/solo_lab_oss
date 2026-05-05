"""Weekly RU Pulse — autonomous Saturday digest.

Pipeline:
    snapshot()  → freeze current corpus into data/snapshots/YYYY-WW.json.gz
    diff()      → compute 5 metrics vs previous snapshot
    render()    → fill pulse_template.j2 with diff data
    judge()     → deterministic brand-voice gate (regex-based)
    publish/park → if PASS: print to stdout / pipe to TG; if FAIL: park in
                   _review/ with reasons
    + non-zero exit on any failure so cron_weekly.sh can TG-alert

This module is deterministic. It does NOT call an LLM. The "analysis"
sentences in the template are filled from corpus context fields (or
left blank if absent). LLM-grounded analysis is an optional future
enhancement; v1 ships pure-deterministic for predictability.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("ru_pulse.weekly")

DATA_DIR = Path(__file__).parent / "data"
SNAP_DIR = DATA_DIR / "snapshots"
REPORTS = Path(__file__).parent / "reports"

LEXICON_PATH = REPORTS / "lexicon_report.json"
TOPICS_PATH = REPORTS / "topics_report.json"
VOICE_PATH = REPORTS / "voice_fingerprint.json"

KEEP_SNAPSHOTS = 8

TABU = re.compile(
    r"(?i)transformative|revolutionary|game.?changing|disrupt|cutting.?edge|"
    r"paradigm.?shift|mind.?blown|THIS IS HUGE|no.?brainer|"
    r"Привет, друзья|Дорогие подписчики|на мой взгляд|"
    r"возможно,|как мне кажется|революция|прорыв|мощный|"
    r"невероятный|потрясающий|латенси|паддинг|healer"
)
EMOJI_AFTER_FIRST_LINE = re.compile(
    r"\n.*[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    r"\U00002700-\U000027BF☀-⛿]"
)
FIRST_PERSON = re.compile(
    r"(?i)\b(я|у меня|попробовал|сломал|проверил|построил|написал|сделал)\b"
)
BULLET_RUN = re.compile(r"(?:^[\s]*[-•*][^\n]*\n){4,}", re.MULTILINE)


@dataclass
class TermDelta:
    term: str
    count_now: int
    count_prev: int
    delta_pct: float
    channels_now: int
    analysis: str = ""


@dataclass
class CadenceShift:
    channel: str
    count_now: int
    count_prev: int
    direction: str   # "up" or "down"


@dataclass
class HypeWatch:
    hype_index_now: float
    hype_delta: float
    direction: str   # "UP" / "DOWN" / "FLAT"
    sample_channels: int


@dataclass
class DiffResult:
    week_current: str
    week_prev: str
    rising: list[TermDelta] = field(default_factory=list)
    falling: list[TermDelta] = field(default_factory=list)
    cadence_shifts: list[CadenceShift] = field(default_factory=list)
    hype: HypeWatch | None = None
    data_ok: bool = False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def snapshot(snap_dir: Path = SNAP_DIR) -> dict:
    """Freeze the three current report JSONs into a weekly snapshot.
    Prunes to the last KEEP_SNAPSHOTS files."""
    snap_dir.mkdir(parents=True, exist_ok=True)
    week = _iso_week(_now_utc())

    if not (LEXICON_PATH.exists() and TOPICS_PATH.exists() and VOICE_PATH.exists()):
        raise FileNotFoundError(
            "Required reports missing. Run analyze + voice_fingerprint + topics first."
        )

    data = {
        "snapshot_week": week,
        "snapshot_ts": int(_now_utc().timestamp()),
        "lexicon": json.loads(LEXICON_PATH.read_text(encoding="utf-8")),
        "topics": json.loads(TOPICS_PATH.read_text(encoding="utf-8")),
        "voice": json.loads(VOICE_PATH.read_text(encoding="utf-8")),
    }
    out = snap_dir / f"{week}.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    # Prune older snapshots; keep the most recent KEEP_SNAPSHOTS by lexicographic order
    snaps = sorted(snap_dir.glob("*.json.gz"))
    for old in snaps[:-KEEP_SNAPSHOTS]:
        try:
            old.unlink()
        except OSError as e:
            LOG.warning("could not prune %s: %s", old, e)

    LOG.info("snapshot wrote %s (week=%s)", out, week)
    return data


def _previous_snapshot(snap_dir: Path = SNAP_DIR) -> dict | None:
    """Return the second-most-recent snapshot (the prev one to compare against)."""
    snaps = sorted(snap_dir.glob("*.json.gz"))
    if len(snaps) < 2:
        return None
    prev = snaps[-2]
    with gzip.open(prev, "rt", encoding="utf-8") as f:
        return json.load(f)


def _aggregate_term_counts(lexicon: dict) -> tuple[Counter, Counter]:
    """Returns (term -> total mentions, term -> distinct channel count)."""
    mentions: Counter[str] = Counter()
    channels_with: dict[str, set[str]] = {}
    for cs in lexicon.get("per_channel", []):
        ch = cs.get("name")
        if not ch:
            continue
        for t, c in cs.get("top_cyr", []):
            mentions[t] += c
            channels_with.setdefault(t, set()).add(ch)
        for t, c in cs.get("top_lat", []):
            mentions[t] += c
            channels_with.setdefault(t, set()).add(ch)
    chcount = Counter({t: len(s) for t, s in channels_with.items()})
    return mentions, chcount


def _compute_term_deltas(now: dict, prev: dict | None) -> tuple[list[TermDelta], list[TermDelta]]:
    if not prev:
        return [], []
    mentions_now, channels_now = _aggregate_term_counts(now)
    mentions_prev, _ = _aggregate_term_counts(prev)

    rising: list[TermDelta] = []
    falling: list[TermDelta] = []

    all_terms = set(mentions_now) | set(mentions_prev)
    for term in all_terms:
        n_now = mentions_now.get(term, 0)
        n_prev = mentions_prev.get(term, 0)
        ch_now = channels_now.get(term, 0)
        if n_now < 5 and n_prev < 5:
            continue
        delta_pct = (n_now - n_prev) / max(n_prev, 1) * 100
        td = TermDelta(
            term=term, count_now=n_now, count_prev=n_prev,
            delta_pct=round(delta_pct, 1), channels_now=ch_now,
        )
        if delta_pct > 0 and n_now >= 5:
            rising.append(td)
        elif delta_pct < 0 and n_prev >= 5:
            falling.append(td)

    rising.sort(key=lambda x: x.delta_pct, reverse=True)
    falling.sort(key=lambda x: x.delta_pct)
    return rising[:5], falling[:5]


def _compute_cadence(now: dict, prev: dict | None) -> list[CadenceShift]:
    if not prev:
        return []
    cad_now = now.get("cadence", {})
    cad_prev = prev.get("cadence", {})
    shifts = []
    for ch, d_now in cad_now.items():
        n_now = d_now.get("posts_last_7d", 0)
        n_prev = cad_prev.get(ch, {}).get("posts_last_7d", 0)
        if n_prev == 0 and n_now == 0:
            continue
        if n_prev == 0:
            ratio = float("inf")
        else:
            ratio = n_now / n_prev
        if ratio >= 2.0 and n_now >= 4:
            shifts.append(CadenceShift(channel=ch, count_now=n_now,
                                       count_prev=n_prev, direction="up"))
        elif ratio <= 0.5 and n_prev >= 4:
            shifts.append(CadenceShift(channel=ch, count_now=n_now,
                                       count_prev=n_prev, direction="down"))
    shifts.sort(key=lambda s: abs(s.count_now - s.count_prev), reverse=True)
    return shifts[:3]


def _compute_hype(now: dict, prev: dict | None,
                  anti_models: set[str]) -> HypeWatch | None:
    if not prev:
        return None

    def hype_index(voice: dict) -> tuple[float, int]:
        total = 0.0
        n = 0
        for ch in voice.get("raw", []):
            if ch.get("name") in anti_models and ch.get("n_posts", 0) > 0:
                caps = ch.get("caps_per_100w", 0.0)
                bullet = ch.get("bullet_share", 0.0)
                listicle = ch.get("listicle_share", 0.0)
                total += caps * 100 + bullet * 50 + listicle * 30
                n += 1
        return (total, n)

    now_total, now_n = hype_index(now)
    prev_total, prev_n = hype_index(prev)
    now_avg = now_total / max(now_n, 1)
    prev_avg = prev_total / max(prev_n, 1)
    delta = now_avg - prev_avg
    if delta > 5:
        direction = "UP"
    elif delta < -5:
        direction = "DOWN"
    else:
        direction = "FLAT"
    return HypeWatch(hype_index_now=round(now_avg, 1),
                     hype_delta=round(delta, 1), direction=direction,
                     sample_channels=now_n)


def diff(now: dict, prev: dict | None, anti_models: set[str]) -> DiffResult:
    week_current = _iso_week(_now_utc())
    week_prev = prev.get("snapshot_week") if prev else "—"
    rising, falling = _compute_term_deltas(
        now.get("lexicon", {}), prev.get("lexicon") if prev else None
    )
    cadence = _compute_cadence(
        now.get("topics", {}), prev.get("topics") if prev else None
    )
    hype = _compute_hype(
        now.get("voice", {}), prev.get("voice") if prev else None, anti_models
    )
    return DiffResult(
        week_current=week_current, week_prev=week_prev,
        rising=rising, falling=falling, cadence_shifts=cadence,
        hype=hype, data_ok=prev is not None,
    )


def render(d: DiffResult) -> str:
    """Render the diff into a TG-HTML markdown post.
    Pure deterministic — no LLM."""
    lines: list[str] = []
    week_n = d.week_current.split("-W")[-1].lstrip("0") or "0"
    today = _now_utc()
    date_display = today.strftime("%-d %b %Y")

    if not d.data_ok:
        lines.append(f"<b>● RU Pulse #{week_n} — {date_display}</b>\n")
        lines.append("Первый запуск без сравнительных данных. Снимок недели "
                     "записан; сравнение будет в следующую субботу.\n")
        return "\n".join(lines)

    if d.rising:
        top = d.rising[0]
        hook = (f"<b>{top.term}</b> +{int(top.delta_pct)}% за неделю "
                f"({top.count_prev} → {top.count_now} упоминаний, "
                f"{top.channels_now} каналов).")
    else:
        hook = "На прошлой неделе статистически значимых сдвигов нет."

    lines.append(f"<b>● RU Pulse #{week_n} — {date_display}</b>\n")
    lines.append(hook + "\n")
    lines.append("<b>Что изменилось за неделю</b>\n")

    for item in d.rising[:3]:
        lines.append(
            f"<b>{item.term}</b> +{int(item.delta_pct)}% неделя к неделе "
            f"({item.count_prev} → {item.count_now} упоминаний, "
            f"{item.channels_now} каналов)."
        )
        if item.analysis:
            lines.append(item.analysis)
        lines.append("")

    if d.falling:
        f = d.falling[0]
        lines.append(
            f"<b>{f.term}</b> −{int(abs(f.delta_pct))}% "
            f"({f.count_prev} → {f.count_now} упоминаний)."
        )
        if f.analysis:
            lines.append(f.analysis)
        lines.append("")

    if d.cadence_shifts:
        lines.append("<b>Кто ускорился, кто замедлился</b>\n")
        for cs in d.cadence_shifts[:3]:
            if cs.count_prev == 0:
                lines.append(
                    f"{cs.channel}: новая активность — "
                    f"0 → {cs.count_now} постов/нед."
                )
                continue
            sign = "+" if cs.direction == "up" else "−"
            ratio = abs(cs.count_now - cs.count_prev) / cs.count_prev * 100
            lines.append(
                f"{cs.channel}: {cs.count_prev} → {cs.count_now} постов/нед "
                f"({sign}{int(ratio)}%)."
            )
        lines.append("")

    if d.hype:
        if d.hype.direction == "UP":
            lines.append(
                "<b>Хайп-индекс</b>\n"
                f"Hype-индекс антимодельных каналов вырос на "
                f"{d.hype.hype_delta:.1f} пункта — больше CAPS, "
                f"больше буллетов. Слежу.\n"
            )
        elif d.hype.direction == "DOWN":
            lines.append(
                "<b>Хайп-индекс</b>\n"
                f"Hype-индекс антимодельных каналов упал на "
                f"{abs(d.hype.hype_delta):.1f} пункта — шума меньше.\n"
            )
        else:
            lines.append(
                "<b>Хайп-индекс</b>\n"
                f"Hype-индекс антимодельных каналов стабилен "
                f"(Δ {d.hype.hype_delta:.1f}). Шум не растёт.\n"
            )

    lines.append("Полный отчёт: solo-lab.dev/pulse · код: github.com/solo-lab/ru_pulse")
    return "\n".join(lines)


def judge(text: str) -> tuple[bool, list[str]]:
    """Deterministic brand-voice gate. Returns (pass, reasons)."""
    reasons: list[str] = []
    tabu_match = TABU.search(text)
    if tabu_match:
        reasons.append(f"tabu word matched: {tabu_match.group(0)!r}")
    if "!" in text:
        reasons.append("exclamation mark in body")
    if EMOJI_AFTER_FIRST_LINE.search(text):
        reasons.append("emoji found after first line")
    if BULLET_RUN.search(text):
        reasons.append("> 3 consecutive bullet lines (listicle)")
    word_count = len(text.split())
    if word_count < 250:
        reasons.append(f"word count {word_count} < 250")
    if word_count > 800:
        reasons.append(f"word count {word_count} > 800")
    if not FIRST_PERSON.search(text):
        # warning, not fail — observational digest may be impersonal
        pass
    return (len(reasons) == 0, reasons)


def publish_to_stdout(text: str) -> None:
    """Default publish path: print to stdout. Wrap with a TG send call
    in the cron wrapper or a dedicated publish script."""
    sys.stdout.write(text + "\n")


_WEEK_RX = re.compile(r"^\d{4}-W\d{2}$")


def park_for_review(text: str, reasons: list[str], review_dir: Path,
                    week: str) -> Path:
    """Park failed post into review dir with diagnostic comment.
    `week` must match `YYYY-Www` (e.g. 2026-W18) — the value flows into the
    output filename, so we reject anything that could escape `review_dir`."""
    if not _WEEK_RX.fullmatch(week):
        raise ValueError(f"week {week!r} must match {_WEEK_RX.pattern}")
    review_dir.mkdir(parents=True, exist_ok=True)
    out = review_dir / f"{week}_pulse.md"
    out.write_text(
        text + f"\n\n<!-- JUDGE FAIL ({len(reasons)} reasons): "
               f"{'; '.join(reasons)} -->\n",
        encoding="utf-8",
    )
    LOG.error("parked for review: %s reasons=%s", out, reasons)
    return out


def run(snap_dir: Path = SNAP_DIR,
        review_dir: Path = Path("/tmp/ru_pulse_review"),
        anti_models: set[str] | None = None) -> int:
    if anti_models is None:
        anti_models = {"gpt_news", "neuralpony", "neuraldvig",
                       "larkinmd07", "belkin_digital"}
    now = snapshot(snap_dir)
    prev = _previous_snapshot(snap_dir)
    d = diff(now, prev, anti_models)
    text = render(d)
    ok, reasons = judge(text)
    if ok:
        publish_to_stdout(text)
        return 0
    park_for_review(text, reasons, review_dir, d.week_current)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Weekly RU Pulse digest")
    ap.add_argument("--snap-dir", type=Path, default=SNAP_DIR)
    ap.add_argument("--review-dir", type=Path, default=Path("/tmp/ru_pulse_review"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(args.snap_dir, args.review_dir)


if __name__ == "__main__":
    sys.exit(main())
