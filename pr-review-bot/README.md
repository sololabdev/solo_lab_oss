# Solo Lab PR Review Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/marketplace-pr--review--bot-yellow?logo=github)](https://github.com/marketplace/actions/solo-lab-pr-review-bot)
[![Solo Lab](https://img.shields.io/badge/by-solo--lab.dev-yellow)](https://solo-lab.dev)

Drop into any GitHub repo, get an automated review on every pull
request. v1 ships a brand-voice + tabu-word lint pass; the code-review
pass lands in v2.

This is the same review bot Solo Lab runs on its own monorepo. It's
distributed as a GitHub Action so any repo can install it in two lines
of YAML.

## What it does (today)

Runs on every `pull_request` open / synchronize event:

1. Fetches the PR diff via the GitHub API.
2. POSTs the diff + PR metadata to the Solo Lab review endpoint.
3. Posts the review back as a comment on the PR.

The v1 endpoint runs a deterministic brand-voice + tabu-word lint:

- Flags hype words (`revolutionary`, `game-changer`, `disrupt`, …) in
  diffed Markdown / docstrings / commit-touched copy.
- Flags AI tells (`leverages cutting-edge`, `delve into`, em-dashes
  used as connectors, …).
- Flags missing `Co-Authored-By` lines in commit messages when the diff
  hints AI assistance.

Code review (logic bugs, security issues, test coverage drops) is
**not** in v1 — it's coming in v2 as a paid feature. v1 is honest about
what it covers; the comment header always lists v1 scope.

## Install

In your repo, create `.github/workflows/pr-review.yml`:

```yaml
name: PR Review
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: sololabdev/pr-review-bot@v1
        with:
          review-style: voice          # voice | code | both
          comment-mode: summary        # summary | inline
```

That's it. The next PR you open gets a review comment.

### With a Pro API key

```yaml
      - uses: sololabdev/pr-review-bot@v1
        with:
          review-style: both
          solo-lab-api-key: ${{ secrets.SOLO_LAB_API_KEY }}
```

Get a key at [solo-lab.dev/pro](https://solo-lab.dev/pro). Free tier is
10 reviews / day per repo; Pro is unlimited.

### Self-hosted endpoint

You can point the action at any compatible endpoint:

```yaml
      - uses: sololabdev/pr-review-bot@v1
        with:
          api-endpoint: https://review.your-company.dev/api/pr-review
```

The protocol is documented in [`docs/api.md`](./docs/api.md).

## Inputs

| name | default | description |
| --- | --- | --- |
| `solo-lab-api-key` | `""` | Optional Pro API key. Free tier without. |
| `review-style` | `voice` | `voice` / `code` / `both`. v1 only `voice`. |
| `comment-mode` | `summary` | `summary` (one comment) or `inline` (per finding). |
| `api-endpoint` | `https://solo-lab.dev/api/pr-review` | Override for self-hosted. |
| `fail-on-findings` | `false` | Set `true` to block merge on findings. |

## Outputs

| name | description |
| --- | --- |
| `finding-count` | Number of findings reported. |
| `review-url` | URL of the posted review comment. |

## Example output

A real review comment looks like this — copy-pasted from the bot
running on Solo Lab's own repo:

```markdown
## Solo Lab PR Review Bot

3 brand-voice findings on this diff. Code-review pass not in v1.

### Findings (3)

- **warn** `README.md`:14 — "revolutionary" is a tabu word; rewrite as a receipt
  ("3× faster on the 4-leader benchmark")
- **info** `docs/quickstart.md`:42 — em-dashes used as connectors look AI-generated;
  Solo Lab voice uses periods or sentence breaks instead
- **warn** commit message — diff touches /docs and looks AI-assisted but commit
  has no Co-Authored-By line

---
Posted by [Solo Lab PR Review Bot](https://solo-lab.dev/pr-review-bot).
v1 covers brand-voice + tabu-word lint; code review lands in v2. Free tier
(10/day) — [upgrade](https://solo-lab.dev/pro) for unlimited.
```

See [`examples/`](./examples) for more.

## What's coming in v2

- Code-review pass (logic bugs, missing tests, dead code, security hotspots).
- Inline review comments anchored to specific diff lines.
- Per-repo voice-rule overrides (`.solo-lab/voice.yml`).
- Self-hostable open-source review server.

The review server itself becomes open-source once it's stable. v1 is
client-only OSS — the action package and protocol are MIT, the hosted
endpoint runs Solo Lab's brand-voice judge under the hood.

## Honest scope

- **v1 — live.** Brand-voice + tabu-word lint. Deterministic. No LLM in
  the hot path; rules are explicit.
- **v1 — live.** Free tier of 10 reviews/day per repo.
- **v2 — accepted, returns "not yet".** Code review. The action accepts
  `review-style: code` today and the server returns a "not yet" finding —
  no surprise charges, no fake outputs.
- **v2 — accepted, returns "not yet".** Inline mode. v1 always posts a
  summary comment; `comment-mode: inline` is accepted for forward
  compatibility.

## Development

```bash
# Lint the entrypoint
shellcheck entrypoint.sh

# Validate the action manifest
python3 -c "import yaml; yaml.safe_load(open('action.yml'))"

# Smoke-test against a local stub
./tests/smoke.sh http://127.0.0.1:8090/api/pr-review
```

## License

MIT — see [LICENSE](./LICENSE).

Built by [Solo Lab](https://solo-lab.dev). Solo dev, autonomous
pipeline, zero-marketing-budget, public receipts.
