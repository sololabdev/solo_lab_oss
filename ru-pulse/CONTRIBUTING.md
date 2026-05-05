# Contributing to RU Pulse

Thank you for your interest in contributing to RU Pulse! This document outlines guidelines for reporting bugs, adding channels, running tests, and maintaining code quality.

## Reporting Bugs

When reporting a security issue related to the injection-defense layers, **do not** open a public issue. Instead, email the maintainers directly.

For general bugs:

1. **Check existing issues** to avoid duplicates
2. **Title:** brief, one-liner (`Parser fails on forwarded posts with media` not `bug`)
3. **Reproduction steps:** exact command and output
4. **Expected vs. actual:** what should happen vs. what happened
5. **Environment:** Python version, OS, corpus.db state (small / large)

Example:
```
Title: verify --mode quarantine crashes on empty corpus

Steps:
1. rm data/corpus.db
2. python -m ru_pulse.verify --mode quarantine --n 10

Expected: "No posts in quarantine" message or graceful exit.
Actual: KeyError in line 42 of verify.py
```

## Adding Channels

To propose a new channel for one of the seven buckets:

1. **Open an issue** with title: `[channel] <channel_name>:<bucket>`
2. **Channel details:**
   - Public `t.me/s/<channel>` proof link
   - Topic area (AI, dev, indie, news, stack-specific, hype, EN peer?)
   - Approximate follower count / post frequency
   - Rationale: why this channel fits the bucket's definition
3. **Approval:** maintainer will run `python -m ru_pulse.probe <channel_name>` to verify liveness and add to `channels.txt`

Example issue:
```
[channel] fastapi_news:stack_specific

Link: https://t.me/s/fastapi_news (public, no MTProto needed)
Followers: ~8k, posts 2-3x/week
Rationale: Python/web framework community, fits stack_specific bucket alongside uvicorn_dev
```

## Running Tests Locally

### Setup

```bash
# Clone the repo
git clone https://github.com/solo-lab/ru_pulse.git
cd ru_pulse

# Install dependencies
pip install -r requirements.txt

# Initialize SQLite corpus (one-time)
python -m ru_pulse.storage
```

### Run tests

```bash
# All tests
python -m pytest ru_pulse/tests/ -v

# Single test file
python -m pytest ru_pulse/tests/test_parser.py -v

# Specific test
python -m pytest ru_pulse/tests/test_parser.py::test_sanitize_catches_known_attacks -v
```

### Test coverage expectations

- Parser tests verify text/msg_id/date extraction from real HTML
- Sanitize tests confirm known injection patterns are caught and normal Russian text passes
- Channel parsing tests handle both file format and comma-separated input
- All tests run offline (no network) and are deterministic

## Style Guide

### Python code

- **Indentation:** 4 spaces (not tabs)
- **Type hints:** required for all function signatures
  ```python
  def parse_date(text: str) -> datetime | None:
      """Extract ISO date from HTML element."""
  ```
- **f-strings only:** use `f"{var}"` not `f'{var}'` or `.format(var)`
- **No bare except:** catch specific exceptions
  ```python
  try:
      response.raise_for_status()
  except requests.HTTPError as e:
      logger.error(f"HTTP {e.response.status_code}")
  ```
- **Docstrings:** module and function docstrings required; single-line for obvious functions
  ```python
  def is_safe(text: str) -> bool:
      """Check if text passes injection scanner."""
  ```

### Commit messages

- **Style:** [Conventional Commits](https://www.conventionalcommits.org/)
  - `feat(sanitize): add pattern for XYZ injection`
  - `fix(fetch): handle 429 with exponential backoff`
  - `docs(README): clarify bucket taxonomy`
  - `test(voice_fingerprint): add centroid assertion`
  - `refactor(storage): extract dedup logic to helper`
- **Scope:** module name (fetch, sanitize, analyze, etc.) or `core` for cross-cutting
- **No emoji:** commit bodies should be plain text for email compatibility
- **Line length:** wrap at 72 chars for commit body

### Markdown

- **Links:** relative within repo (`./README.md` not absolute URLs)
- **Code blocks:** use triple-backtick with language tag
  ```
  ```python
  import ru_pulse
  ```
  ```

## Reporting Results

If you run a full fetch against the 50-channel taxonomy, please open an issue with:

- **Summary:** total posts, new/dup/quarantined breakdown
- **Corpus size:** corpus.db file size
- **Dates spanned:** earliest/latest post in corpus
- **Quarantine highlights:** interesting patterns or false positives
- **Notable topics:** trends observed across buckets

Example:
```
[results] 50-channel corpus run 2026-05-05

Posts: 4,821 total (3,205 new, 1,610 dup, 6 quarantined)
Corpus: 18 MB, spans 2026-04-01 to 2026-05-05
Quarantine: 4 false positives on "instructions for RAG pipeline", 2 legit stops

Trends: RAG + LLM evaluation dominates ai_core; Rust adoption in stack_specific
```

## Codeowners & Maintenance

Currently maintained by the Solo Lab research team. Pull requests will be reviewed for:

- Correctness of parser/sanitizer logic
- No regression in test coverage
- Compliance with style guide
- Type safety

Maintainers will not accept:

- Direct corpus.db commits (gitignored intentionally)
- Hard-coded API tokens or credentials
- Telethon / MTProto client code (only public `t.me/s/` HTML allowed)

## Questions?

Open an issue or check the [README.md](./README.md) for usage examples.
