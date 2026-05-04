# PR Review Bot — API protocol

The action is a thin client. It POSTs JSON to a single endpoint and
expects JSON back. Anyone can implement a compatible server.

## Endpoint

```
POST {api-endpoint}
Content-Type: application/json
Authorization: Bearer {solo-lab-api-key}     # optional
User-Agent: solo-lab-pr-review-bot/1.0 (+{owner/repo})
```

## Request body

```json
{
  "repo":         "owner/repo",
  "pr_number":    42,
  "title":        "feat: add brand-voice judge",
  "body":         "PR description in markdown",
  "base_sha":     "abc123",
  "head_sha":     "def456",
  "review_style": "voice",
  "comment_mode": "summary",
  "diff":         "diff --git a/... (raw unified diff, capped at 200 KB)"
}
```

## Response body — 200 OK

```json
{
  "ok":       true,
  "summary":  "Top-level markdown summary string posted in the comment header.",
  "findings": [
    {
      "severity": "warn",
      "file":     "README.md",
      "line":     14,
      "message":  "\"revolutionary\" is a tabu word; rewrite as a receipt"
    }
  ],
  "tier":     "free",
  "remaining": 9
}
```

- `findings[].severity` ∈ {`info`, `warn`, `error`}.
- `findings[].file` and `findings[].line` are optional (omit for
  PR-wide findings such as commit-message issues).
- `tier` and `remaining` are informational; the action does not depend
  on them.

## Response body — 429 Rate Limited

```json
{ "ok": false, "message": "free tier limit (10/day) reached" }
```

The action treats 429 as non-fatal and exits 0 with a log line.

## Response body — anything else

The action logs the status code and body, exits 0, and posts no
comment. It never fails the host workflow on a server-side error
unless `fail-on-findings: true` AND findings ≥ 1.
