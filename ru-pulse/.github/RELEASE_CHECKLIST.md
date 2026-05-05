# Release Checklist — RU Pulse

Run through this list before `git push` to a public remote or any tagged release.

## Secrets & private data

- [ ] `grep -rE "(SECRET|TOKEN|API_KEY|PASSWORD|BEARER)" .` returns no real values
- [ ] No reference to `/etc/openclaw/secrets.env` in committed code
- [ ] No reference to `~/.openclaw/credentials/` in committed code
- [ ] No Tema-specific paths (`/home/temaclaw/...`) inside source files (READMEs may show repo-relative paths only)
- [ ] `.env` files not committed
- [ ] `data/corpus.db` confirmed gitignored
- [ ] `reports/*.json` confirmed gitignored (large analysis outputs)

## Code quality

- [ ] `python -m pytest ru_pulse/tests/ -v` — all green
- [ ] No `TODO` / `FIXME` / `XXX` markers in `*.py` (or, if any remain, justified in PR)
- [ ] `python -m ru_pulse.fetch --channels "addmeto:dev" --max-posts 5` runs cleanly end-to-end
- [ ] `python -m ru_pulse.analyze` runs to completion on the local corpus
- [ ] `requirements.txt` minimal and pinned

## Repo meta

- [ ] `LICENSE` (MIT) in place
- [ ] `README.md` quickstart works as written for a clean clone
- [ ] `CHANGELOG.md` updated for this version
- [ ] `CONTRIBUTING.md` accurate
- [ ] `.github/ISSUE_TEMPLATE/*.md` present (bug_report, channel_proposal)
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` present
- [ ] No `.github/workflows/` with secrets references unless intended public

## Tagging

- [ ] Version bumped in `CHANGELOG.md`
- [ ] Tag: `git tag v0.1.0 -m "Initial public release"`
- [ ] `git push origin main && git push origin v0.1.0`

## Post-push

- [ ] GitHub repo description set
- [ ] Topics added: `telegram`, `corpus`, `russian`, `nlp`, `linguistic-analysis`, `voice-analysis`
- [ ] Pinned README screenshot of `dashboard.md` (optional)
