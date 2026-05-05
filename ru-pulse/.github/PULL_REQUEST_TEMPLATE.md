## Summary

<!-- 1-3 sentences: what changed and why. -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] New channel(s) added
- [ ] Refactor / cleanup
- [ ] Docs

## Test plan

- [ ] `python -m pytest ru_pulse/tests/ -v` — green
- [ ] (if scraper-touching) Smoke test: `python -m ru_pulse.fetch --channels "<one>:<bucket>" --max-posts 5`
- [ ] (if analyzer-touching) `python -m ru_pulse.analyze` runs to completion
- [ ] No new dependencies (or, if added, pinned in `requirements.txt` and justified)

## Etiquette / safety check

- [ ] No reduction of `REQ_DELAY` below 3s
- [ ] No removal of sanitize layers
- [ ] No commit of `data/corpus.db` or `reports/*.json` (size)
- [ ] No private channel handles or credentials in committed files

## Screenshots / logs (optional)
