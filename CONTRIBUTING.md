# Contributing

Thanks for taking a look. This repo bundles three small libraries —
`zone-renderer`, `structural-judge`, `opus-4-7-context-test` — each with
its own `requirements.txt` and tests. PRs and issues welcome on any of
them.

## How to run tests

Each library has its own `tests/` directory. From the repo root:

```bash
cd zone-renderer            && python -m pytest tests/
cd ../structural-judge      && python -m pytest tests/
cd ../opus-4-7-context-test && python -m pytest tests/
```

Tests are pure-Python, no API keys required, no network. They run in
under a second per library.

## How to report a bug

Open an issue using one of the templates:

- **Bug report** — anything that crashes, returns wrong output, or
  misbehaves: [`.github/ISSUE_TEMPLATE/bug_report.md`](./.github/ISSUE_TEMPLATE/bug_report.md)
- **Methodology dispute** — for arguments specifically about the
  `opus-4-7-context-test` benchmark setup, scoring, or claims:
  [`.github/ISSUE_TEMPLATE/methodology_dispute.md`](./.github/ISSUE_TEMPLATE/methodology_dispute.md)

Reproduction steps that fit in 60 seconds get fixed first. A failing
test case in a PR gets fixed even faster.

## How to add a benchmark for opus-4-7-context-test

The benchmark is just a JSON file plus a corpus directory. To add your
own: drop your codebase under a directory of your choice, write a
`questions.json` shaped like `opus-4-7-context-test/fixtures/sample_repo/questions.json`
(each question has `id`, `prompt`, `expected_substrings`, `size_bucket`),
and run `python benchmark_opus_47.py --corpus-dir /path/to/your/repo
--questions /path/to/questions.json`. Substring scoring is in
`score_run.py`; if your domain needs a different scorer, fork the file
and submit a PR with a short rationale. Open a methodology-dispute
issue first if you think the scoring is wrong — easier to align before
code than after.

## Solo Lab brand context

This repo is auxiliary OSS pulled out of the Solo Lab content
infrastructure ([solo-lab.dev](https://solo-lab.dev)). The brand is a
faceless content stack for solo founders; these libraries are the parts
that turned out to be useful on their own. They are not a standalone
product, there is no roadmap, and there is no paid tier. They get
maintained because the brand uses them daily — that is the whole
support contract. PRs that fit the existing aesthetic (small,
single-file, replace-a-SaaS, no async magic when sync works) get merged
quickly.

## License + signoff

Everything here is MIT. By submitting a PR you agree your contribution
is licensed under MIT and that you have the right to submit it.

We use a lightweight DCO. Add a `Signed-off-by` line to each commit:

```
git commit -s -m "your message"
```

That appends `Signed-off-by: Your Name <you@example.com>` and certifies
you wrote the code (or have permission to contribute it) per the
[Developer Certificate of Origin](https://developercertificate.org/).
No CLA, no corporate forms.
