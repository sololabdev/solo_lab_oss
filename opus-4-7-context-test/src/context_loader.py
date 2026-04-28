"""
Build deterministic context loads at any target token count for the Opus 4.7
1M-context benchmark.

Default behaviour (out-of-the-box, works on a fresh clone):
- Loads `fixtures/sample_repo/` shipped in this repo.
- Useful for kicking the tires; the ~6 KB of fixture code won't fill 150K
  tokens, so the loader pads with deterministic noise to hit the target.

To benchmark your OWN codebase:
- Pass `--corpus-dir /path/to/your/repo` to point the loader at your tree.
- The loader pulls all `.py`, `.md`, `.json` files recursively in
  deterministic (sorted) order until the token target is reached.
- Write your own `questions.json` against your codebase.

Tokenisation: anthropic.Anthropic().messages.count_tokens for accuracy, OR
char/4 estimate if `--offline` (free, slightly less accurate).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "fixtures" / "sample_repo"
DEPS_DIR = Path(__file__).resolve().parent / "deps"
DEPS_DIR.mkdir(exist_ok=True)


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def corpus_from_dir(corpus_dir: Path) -> list[tuple[str, str]]:
    """Pull all .py / .md / .json files from a directory tree, sorted, in
    deterministic order. Used for both the bundled fixture repo and any
    user-supplied --corpus-dir."""
    items: list[tuple[str, str]] = []
    if not corpus_dir.exists():
        return items
    # Order: .py first (the substantive code), then .md docs, then .json configs.
    for ext, label in (("*.py", "FILE"), ("*.md", "DOC"), ("*.json", "CONFIG")):
        for f in sorted(corpus_dir.rglob(ext)):
            rel = f.relative_to(corpus_dir)
            items.append((f"# {label}: {rel}\n", read_file(f)))
    return items


def deps_corpus() -> list[tuple[str, str]]:
    """API reference docs the user has dropped into benchmark/src/deps/.
    Returns empty if directory is missing or empty."""
    items: list[tuple[str, str]] = []
    if not DEPS_DIR.exists():
        return items
    for f in sorted(DEPS_DIR.glob("*.md")) + sorted(DEPS_DIR.glob("*.txt")):
        items.append((f"# DEP: {f.name}\n", read_file(f)))
    return items


def assemble(target_tokens: int, count_tokens, corpus_dir: Path) -> str:
    """Concatenate corpus from corpus_dir + optional deps + padding noise
    until count_tokens(text) >= target. Pads with deterministic filler
    when the corpus is smaller than the target (the common case for the
    bundled fixture repo at 150K+ targets)."""
    layers = corpus_from_dir(corpus_dir)
    if target_tokens > 200_000:
        layers += deps_corpus()
    out: list[str] = []
    for i, (label, body) in enumerate(layers, start=1):
        out.append(label + body + "\n\n")
        if i % 10 == 0 and count_tokens("".join(out)) >= target_tokens:
            break
    text = "".join(out)
    cur = count_tokens(text)
    # Pad with deterministic filler if we're short of target.
    if cur < target_tokens:
        pad_unit = (
            "# pad: deterministic filler line for token-target match. "
            * 8 + "\n"
        )
        while cur < target_tokens:
            text += pad_unit * 50
            cur = count_tokens(text)
    return text


def build_loads(target_tokens_list: list[int], client,
                corpus_dir: Path) -> dict[int, str]:
    def cnt(t: str) -> int:
        try:
            r = client.messages.count_tokens(
                model="claude-opus-4-7",
                messages=[{"role": "user", "content": t}],
            )
            return int(r.input_tokens)
        except (RuntimeError, AttributeError, OSError):
            # Fallback estimate: 1 token per ~4 chars (Claude family rule of thumb)
            return len(t) // 4

    out: dict[int, str] = {}
    for tgt in target_tokens_list:
        out[tgt] = assemble(tgt, cnt, corpus_dir)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--corpus-dir", type=Path, default=FIXTURES_DIR,
        help="Directory whose .py/.md/.json files form the corpus. "
             f"Default: {FIXTURES_DIR.relative_to(PROJECT_ROOT)} "
             "(small bundled fixture repo)."
    )
    ap.add_argument(
        "--offline", action="store_true",
        help="Skip anthropic.count_tokens and use char/4 estimate. "
             "Faster + free, slightly less accurate token targeting."
    )
    ap.add_argument("--targets", type=int, nargs="+",
                    default=[150_000, 500_000, 700_000])
    args = ap.parse_args()

    if not args.corpus_dir.exists():
        print(f"corpus-dir does not exist: {args.corpus_dir}", file=sys.stderr)
        sys.exit(2)

    if args.offline:
        class _FakeClient:
            class messages:
                @staticmethod
                def count_tokens(**kwargs):
                    raise RuntimeError("offline")
        client = _FakeClient()
    else:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            sys.exit("ANTHROPIC_API_KEY not set (or use --offline)")
        client = anthropic.Anthropic(api_key=key)

    loads = build_loads(args.targets, client, args.corpus_dir)
    cache_dir = Path(__file__).resolve().parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    for tgt, text in loads.items():
        p = cache_dir / f"load_{tgt}.txt"
        p.write_text(text)
        print(f"{tgt}: wrote {p} ({len(text):,} chars from {args.corpus_dir})")
