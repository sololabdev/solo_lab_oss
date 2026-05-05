# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Reporting a Vulnerability

Two channels, in order of preference:

1. GitHub Security Advisory: open a private advisory at https://github.com/solo-lab/ru_pulse/security/advisories/new
2. Email: security@solo-lab.dev

Include reproduction steps, affected version, and impact assessment. Encrypted reports welcome; ask for a key.

## Disclosure Window

90 days from acknowledgment to public disclosure. Earlier if a fix ships and is adopted; later only by mutual agreement.

## In Scope

- Prompt-injection vectors in scraped Telegram/web content reaching downstream LLM consumers
- SQL injection in any query path (the corpus store, bucket filters, CLI inputs)
- Path traversal via CLI arguments (`--out`, `--config`, channel/bucket names)
- Auth/credential leakage in logs or error output
- Bypass of the 3-layer sanitize.scan defense

## Out of Scope

- Third-party dependency CVEs — track via Dependabot; report upstream
- Self-DOS against the polite rate-limited fetcher (it is rate-limited by design)
- Issues requiring a malicious local user with filesystem write access
- Social engineering of channel operators

## Acknowledgment

We acknowledge reports within 72 hours. Reporters who follow this policy are credited in CHANGELOG.md and the advisory unless they request anonymity. No bug bounty at this time.
