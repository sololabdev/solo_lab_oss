# Solo Lab PR Review Bot — GitHub Action runtime
#
# Tiny alpine + curl + jq + gh CLI. The action does no heavy lifting
# locally; it just fetches the PR diff, hands it to the Solo Lab API,
# and posts the response back via gh. Cold-start ~3s.
FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    curl \
    jq \
    git \
    github-cli \
    && rm -rf /var/cache/apk/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
