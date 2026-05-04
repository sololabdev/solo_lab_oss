#!/usr/bin/env bash
# Solo Lab PR Review Bot entrypoint.
#
# Runs inside the Action's docker container. Reads PR context from the
# GitHub Actions environment, fetches the diff, posts it to the Solo Lab
# API, and writes the response back as a PR review comment via `gh`.
#
# Inputs (all set by action.yml):
#   INPUT_SOLO_LAB_API_KEY   optional API key (free tier without)
#   INPUT_REVIEW_STYLE       voice | code | both
#   INPUT_COMMENT_MODE       summary | inline
#   INPUT_API_ENDPOINT       https://solo-lab.dev/api/pr-review
#   INPUT_FAIL_ON_FINDINGS   true | false
#
# Required GitHub-supplied env:
#   GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH, GITHUB_OUTPUT
set -euo pipefail

log()  { printf '[pr-review-bot] %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

: "${GITHUB_TOKEN:?GITHUB_TOKEN is required (set permissions: pull-requests: write in workflow)}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY missing — not running in Actions?}"
: "${GITHUB_EVENT_PATH:?GITHUB_EVENT_PATH missing — not a pull_request event?}"

REVIEW_STYLE="${INPUT_REVIEW_STYLE:-voice}"
COMMENT_MODE="${INPUT_COMMENT_MODE:-summary}"
API_ENDPOINT="${INPUT_API_ENDPOINT:-https://solo-lab.dev/api/pr-review}"
FAIL_ON_FINDINGS="${INPUT_FAIL_ON_FINDINGS:-false}"
API_KEY="${INPUT_SOLO_LAB_API_KEY:-}"

case "${REVIEW_STYLE}" in
  voice|code|both) : ;;
  *) fail "review-style must be one of voice|code|both, got '${REVIEW_STYLE}'" ;;
esac
case "${COMMENT_MODE}" in
  summary|inline) : ;;
  *) fail "comment-mode must be one of summary|inline, got '${COMMENT_MODE}'" ;;
esac

PR_NUMBER="$(jq -r '.pull_request.number // .number // empty' "${GITHUB_EVENT_PATH}")"
[[ -n "${PR_NUMBER}" ]] || fail "could not read PR number from event payload"

PR_TITLE="$(jq -r '.pull_request.title // ""' "${GITHUB_EVENT_PATH}")"
PR_BODY="$(jq -r '.pull_request.body // ""'  "${GITHUB_EVENT_PATH}")"
PR_BASE="$(jq -r '.pull_request.base.sha // ""' "${GITHUB_EVENT_PATH}")"
PR_HEAD="$(jq -r '.pull_request.head.sha // ""' "${GITHUB_EVENT_PATH}")"

log "repo=${GITHUB_REPOSITORY} pr=#${PR_NUMBER} style=${REVIEW_STYLE} mode=${COMMENT_MODE}"

# Fetch the diff via the GitHub API. We use `gh` over curl so we
# inherit the runner's GITHUB_TOKEN auth. Cap the diff at 200 KB —
# anything larger gets truncated server-side anyway and we want to
# keep the request small.
export GH_TOKEN="${GITHUB_TOKEN}"
DIFF_FILE="$(mktemp)"
trap 'rm -f "${DIFF_FILE}"' EXIT

if ! gh api \
      -H "Accept: application/vnd.github.v3.diff" \
      "/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}" \
      > "${DIFF_FILE}"; then
  fail "could not fetch PR diff (check workflow has 'pull-requests: read')"
fi

DIFF_BYTES="$(wc -c < "${DIFF_FILE}")"
log "fetched diff: ${DIFF_BYTES} bytes"
if (( DIFF_BYTES > 200000 )); then
  log "diff > 200KB; truncating to 200KB before upload"
  head -c 200000 "${DIFF_FILE}" > "${DIFF_FILE}.trunc"
  mv "${DIFF_FILE}.trunc" "${DIFF_FILE}"
fi

REQUEST_FILE="$(mktemp)"
trap 'rm -f "${DIFF_FILE}" "${REQUEST_FILE}"' EXIT

jq -n \
  --arg repo  "${GITHUB_REPOSITORY}" \
  --arg pr    "${PR_NUMBER}" \
  --arg title "${PR_TITLE}" \
  --arg body  "${PR_BODY}" \
  --arg base  "${PR_BASE}" \
  --arg head  "${PR_HEAD}" \
  --arg style "${REVIEW_STYLE}" \
  --arg mode  "${COMMENT_MODE}" \
  --rawfile diff "${DIFF_FILE}" \
  '{
    repo: $repo,
    pr_number: ($pr | tonumber),
    title: $title,
    body: $body,
    base_sha: $base,
    head_sha: $head,
    review_style: $style,
    comment_mode: $mode,
    diff: $diff
  }' > "${REQUEST_FILE}"

# Call the Solo Lab API. Send the API key as a Bearer header iff set.
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "${DIFF_FILE}" "${REQUEST_FILE}" "${RESPONSE_FILE}"' EXIT

CURL_AUTH=()
if [[ -n "${API_KEY}" ]]; then
  CURL_AUTH=(-H "Authorization: Bearer ${API_KEY}")
fi

HTTP_CODE="$(
  curl -sS -o "${RESPONSE_FILE}" -w '%{http_code}' \
    --max-time 30 \
    -X POST \
    -H 'Content-Type: application/json' \
    -H "User-Agent: solo-lab-pr-review-bot/1.0 (+${GITHUB_REPOSITORY})" \
    "${CURL_AUTH[@]}" \
    --data-binary "@${REQUEST_FILE}" \
    "${API_ENDPOINT}" || echo '000'
)"

log "API responded ${HTTP_CODE}"

if [[ "${HTTP_CODE}" == "429" ]]; then
  MSG="$(jq -r '.message // "rate limited"' "${RESPONSE_FILE}" 2>/dev/null || echo "rate limited")"
  log "rate-limited: ${MSG}"
  log "free tier is 10 reviews/day per repo; upgrade at https://solo-lab.dev/pro"
  exit 0
fi
if [[ "${HTTP_CODE}" != "200" ]]; then
  log "API call failed (HTTP ${HTTP_CODE}); skipping review post"
  log "body: $(head -c 500 "${RESPONSE_FILE}")"
  exit 0  # never fail the host workflow on our outage
fi

# Validate response shape: { ok: true, findings: [{file?, line?, message, severity}], summary }
if ! jq -e '.ok == true and (.findings|type=="array") and (.summary|type=="string")' \
        "${RESPONSE_FILE}" > /dev/null; then
  log "API returned malformed JSON; skipping review post"
  exit 0
fi

FINDING_COUNT="$(jq '.findings | length' "${RESPONSE_FILE}")"
SUMMARY="$(jq -r '.summary' "${RESPONSE_FILE}")"
log "got ${FINDING_COUNT} finding(s)"

# Format the markdown body. Always include header + summary + footer.
COMMENT_FILE="$(mktemp)"
trap 'rm -f "${DIFF_FILE}" "${REQUEST_FILE}" "${RESPONSE_FILE}" "${COMMENT_FILE}"' EXIT

{
  printf '## Solo Lab PR Review Bot\n\n'
  printf '%s\n\n' "${SUMMARY}"
  if (( FINDING_COUNT > 0 )); then
    printf '### Findings (%s)\n\n' "${FINDING_COUNT}"
    jq -r '
      .findings[] |
      "- **\(.severity // "info")** "
      + (if .file then "`\(.file)`" else "" end)
      + (if .line then ":\(.line)" else "" end)
      + (if .file or .line then " — " else "" end)
      + (.message // "")
    ' "${RESPONSE_FILE}"
    printf '\n'
  else
    printf 'No findings. Ship it.\n\n'
  fi
  printf -- '---\n'
  printf 'Posted by [Solo Lab PR Review Bot](https://solo-lab.dev/pr-review-bot). '
  printf 'v1 covers brand-voice + tabu-word lint; code review lands in v2. '
  if [[ -z "${API_KEY}" ]]; then
    printf 'Free tier (10/day) — [upgrade](https://solo-lab.dev/pro) for unlimited.\n'
  else
    printf 'Pro tier active.\n'
  fi
} > "${COMMENT_FILE}"

# Post the review. `gh pr review --comment` posts a top-level review.
# Falls back to a plain issue comment if review posting fails (e.g. the
# user's workflow only granted issues:write, not pull-requests:write).
REVIEW_URL=""
if gh pr comment "${PR_NUMBER}" \
      --repo "${GITHUB_REPOSITORY}" \
      --body-file "${COMMENT_FILE}" \
      > /tmp/pr-comment.out 2>&1; then
  REVIEW_URL="$(grep -oE 'https://[^ ]+' /tmp/pr-comment.out | head -n1 || true)"
  log "posted comment: ${REVIEW_URL:-ok}"
else
  log "could not post comment (check workflow has 'pull-requests: write'):"
  cat /tmp/pr-comment.out >&2 || true
fi

# Emit Action outputs.
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    printf 'finding-count=%s\n' "${FINDING_COUNT}"
    printf 'review-url=%s\n'    "${REVIEW_URL}"
  } >> "${GITHUB_OUTPUT}"
fi

if [[ "${FAIL_ON_FINDINGS}" == "true" && "${FINDING_COUNT}" -gt 0 ]]; then
  log "fail-on-findings=true and findings>0 → exiting non-zero"
  exit 1
fi
exit 0
