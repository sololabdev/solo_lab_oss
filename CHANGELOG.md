# Changelog

All notable changes to this repo are tracked here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the repo
itself is a bundle of three independently-versioned libraries, so this
log records repo-level changes (root README, contribution scaffolding,
cross-library housekeeping). Per-library changelogs live inside each
library directory.

## [Unreleased] — 2026-05-05

### Added

- New library: **`cache-lab/`** — stdlib-only benchmark of real prompt-cache
  hit rate and billed savings across 10 production LLMs via OpenRouter
  (Claude Haiku/Sonnet/Opus, GPT-4o family, GPT-5.5, Gemini 2.5 Flash/Pro,
  DeepSeek v3.1, Llama 3.3-70b). Includes prefix-size scaling
  (5K/30K/100K), provider-pin sanity tests, BudgetTracker, append-write
  JSONL, 10 unit tests. Backs the upcoming "Real cached-token discounts"
  post.

## [Unreleased] — 2026-04-29

### Added

- HN-day polish on the root README (badges, 60-second reproduction
  block, sample output excerpt). Commit `bc183ad`.

### Changed

- `opus-4-7-context-test` README: post title and hypothesis updated to
  match the actual run findings. Commit `2a25f12`.

### Fixed

- Root README: removed a duplicated bundled-fixture paragraph.
  Commit `8094339`.

## [0.1.0] — 2026-04-28

### Added

- Initial public release of the three libraries: `zone-renderer`,
  `structural-judge`, `opus-4-7-context-test`.
- Code-review fixes and first unit-test coverage across all three
  libraries.
- Root README, root LICENSE (MIT), `.gitignore`.
