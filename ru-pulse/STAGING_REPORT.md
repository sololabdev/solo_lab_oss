# ru_pulse OSS staging report

**Status: READY** — pending Tema confirm on push to `sololabdev/ru_pulse`.

**Staged: 2026-05-03 12:36 UTC** by autonomous run + manual finish.

---

## Verdict
- 216 tests pass, 12 skip (voice_lint tests skip cleanly when
  `reports/voice_fingerprint.json` is absent — by design for public
  distribution; users generate their own from their own corpus).
- Manual secret scan: no API key / Tema-personal / `/home/temaclaw/`
  references in any source file.
- Package importable from clean tree (`import ru_pulse` works).
- All `cron_*.sh` and `self_improve.sh` excluded — they hardcode
  `/home/temaclaw/solo-lab-system/research/ru_pulse/` paths and would
  not work on a fresh install. The README documents the cron pattern
  for users to register on their own systems.

## Files copied (28 production + tests + meta)
- Top-level: `LICENSE`, `README.md`, `CHANGELOG.md`, `CITATION.cff`,
  `CONTRIBUTING.md`, `SECURITY.md`, `pyproject.toml`,
  `requirements.txt`, `py.typed`, `__init__.py`, `.gitignore`,
  `.github/`
- Modules: `analyze.py`, `daily_incremental.py`, `dashboard.py`,
  `diaspora_lens.py`, `fetch.py`, `probe.py`, `publish_to_tg.py`,
  `sanitize.py`, `storage.py`, `topics.py`, `verify.py`,
  `voice_fingerprint.py`, `voice_lint.py`, `weekly_pulse.py`
- Public seed list: `channels.txt` (50 channels)
- Tests: full `tests/` dir (228 source tests including 108 fuzz)

## Files / dirs excluded (with reason)

| Excluded | Reason |
|---|---|
| `data/` | 295 MB SQLite corpus + snapshots; private |
| `channels_v2.txt` | 241-channel private expansion list (the bigger one); `channels.txt` is the 50-channel public seed and stays |
| `reports/` | 4.2 MB of competitor analysis, lens reports, cross-corpus comparisons, outreach drafts; private |
| `cron_*.sh` (`backup`, `daily`, `healthcheck`, `weekly`) | Hardcoded `/home/temaclaw/...` paths; users register their own crons |
| `self_improve.sh` | Same — hardcoded local paths |
| `reminder_30day.sh` | One-shot scheduled reminder for Tema's 30-day verdict; not relevant for OSS users |
| `checkpoint.sh` | Internal dev workflow |
| `__pycache__/`, `*.egg-info/`, `.pytest_cache/` | Build artifacts |

## Test result

```
216 passed, 12 skipped in 0.39s
```

The 12 skips are `tests/test_voice_lint.py` — they require a populated
`reports/voice_fingerprint.json` which is intentionally not in the
public distribution. The skip condition is at module level
(`pytestmark = pytest.mark.skipif(not _FP_PATH.exists(), reason=...)`)
with a clear message pointing users at `python -m ru_pulse.voice_fingerprint`.

## Secret scan

Patterns scanned: `sk-or-v1-…`, `sk-ant-…`, `ghp_…`, `AKIA[A-Z0-9]{16}`,
TG bot tokens (`\d{8,}:AAH…`), Stripe (`sk_live_`, `sk_test_`),
`/home/temaclaw/`, `temaclaw@gmail`, `temaclaw`, `tema`, `aurelie`,
`sololabru`, `sololabdeven`. **No hits in any source file.**

The only `/home/temaclaw/...` reference is inside
`.github/RELEASE_CHECKLIST.md` line 10 — and it's the rule itself
("No Tema-specific paths (`/home/temaclaw/...`) inside source files"),
which is correct context, not a leak.

## What's NOT done (waiting for Tema)

- `git init` + remote push to `sololabdev/ru_pulse` — held per CEO
  autonomy: public OSS push is launch-class, requires confirm.
- Show HN slot Tue 2026-05-13 09:00 UTC — default per
  `LAUNCH_PACKAGE.md`; needs Tema confirm.
- Voice-lint distribution decision (inside ru_pulse vs separate repo
  per BRAND.md §9) — defaulted to "inside ru_pulse for v0.1" since
  the existing CHANGELOG already markets voice_lint as part of the
  package.

## Next push command (Tema runs after confirming)

```bash
cd /home/temaclaw/solo-lab-oss-rupulse
git init -b main
git add -A
git commit -m "ru_pulse 0.2.1 — initial public release"
git remote add origin git@github.com:sololabdev/ru_pulse.git
git push -u origin main
```

After push, tag the release:

```bash
git tag -a v0.2.1 -m "v0.2.1 — Phase II + operational hardening"
git push origin v0.2.1
```
