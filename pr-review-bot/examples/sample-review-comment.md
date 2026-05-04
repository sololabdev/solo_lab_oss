# Example review comment

What the bot posts on a real PR. Copy this into a GitHub PR
preview to see how it renders.

---

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
