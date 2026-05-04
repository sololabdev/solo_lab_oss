#!/usr/bin/env bash
# Smoke-test the review API end-to-end.
#
#   ./tests/smoke.sh https://solo-lab.dev/api/pr-review
#   ./tests/smoke.sh http://127.0.0.1:8090/api/pr-review
#
# Sends a synthetic diff that includes one tabu word + one em-dash usage
# and asserts the response shape. Exit non-zero on any check that fails.
set -euo pipefail

ENDPOINT="${1:-http://127.0.0.1:8090/api/pr-review}"
echo "[smoke] target: ${ENDPOINT}"

REQ_FILE="$(mktemp)"
RESP_FILE="$(mktemp)"
trap 'rm -f "${REQ_FILE}" "${RESP_FILE}"' EXIT

cat > "${REQ_FILE}" <<'JSON'
{
  "repo": "sololabdev/test-repo",
  "pr_number": 1,
  "title": "feat: revolutionary new thing",
  "body":  "This is a game-changer — disrupting the space.",
  "base_sha": "0000000",
  "head_sha": "1111111",
  "review_style": "voice",
  "comment_mode": "summary",
  "diff": "diff --git a/README.md b/README.md\n+++ b/README.md\n@@\n+Revolutionary new feature — game-changing.\n"
}
JSON

HTTP_CODE="$(
  curl -sS -o "${RESP_FILE}" -w '%{http_code}' \
    -X POST -H 'Content-Type: application/json' \
    --data-binary "@${REQ_FILE}" \
    --max-time 10 \
    "${ENDPOINT}" || echo '000'
)"

echo "[smoke] HTTP ${HTTP_CODE}"
echo "[smoke] body: $(head -c 400 "${RESP_FILE}")"

if [[ "${HTTP_CODE}" != "200" ]]; then
  echo "[smoke] FAIL: expected 200" >&2
  exit 1
fi

# Validate response shape with jq.
if ! jq -e '.ok == true and (.findings|type=="array") and (.summary|type=="string")' \
      "${RESP_FILE}" > /dev/null; then
  echo "[smoke] FAIL: response missing required fields (ok, findings[], summary)" >&2
  exit 1
fi

# We seeded "revolutionary" + "game-changer" + em-dash; expect ≥1 finding.
N="$(jq '.findings | length' "${RESP_FILE}")"
if (( N < 1 )); then
  echo "[smoke] FAIL: expected ≥1 finding for tabu words, got 0" >&2
  exit 1
fi

echo "[smoke] OK: ${N} finding(s) returned"
