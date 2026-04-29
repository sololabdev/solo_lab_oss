# Changelog

All notable changes to this repo are tracked here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the repo
itself is a bundle of three independently-versioned libraries, so this
log records repo-level changes (root README, contribution scaffolding,
cross-library housekeeping). Per-library changelogs live inside each
library directory.

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
