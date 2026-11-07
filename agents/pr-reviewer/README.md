# claude-review

Review a GitHub pull request and post a comment with the same four sections every time:

```
**Summary of changes**        2-3 sentences
**Identified risks**          bullet list, file:line where possible
**Improvement suggestions**   bullet list
**Confidence score:**         Low | Medium | High
```

Two engines, one output contract:

| Engine | Needs | What it does |
|---|---|---|
| `local` (default) | nothing but network to GitHub | deterministic static analysis of the diff: secrets, injection sinks, TLS off, swallowed errors, shrinking tests, lockfile drift, schema changes, API removals, diff size |
| `claude` | `ANTHROPIC_API_KEY` | sends the diff to the Anthropic API, parses the four sections, falls back to `local` and says so if the call fails |

The default engine matters: a review bot that costs money per PR and returns something
different every run is hard to trust. `local` is free, reproducible, and runs in CI without
a key — the model is the upgrade, not the requirement.

## Install

```bash
git clone --depth 1 https://github.com/dycygds/claude-builder-kit
alias claude-review="$PWD/claude-builder-kit/agents/pr-reviewer/claude-review"
```

No dependencies. Python 3.8+.

## Usage

```bash
# CLI, exactly as specified in the issue
claude-review --pr https://github.com/owner/repo/pull/123

# short form, write to a file
claude-review --pr owner/repo#123 --out review.md

# post it as a PR comment (needs GITHUB_TOKEN with pull-requests: write)
GITHUB_TOKEN=ghp_xxx claude-review --pr owner/repo#123 --comment

# machine-readable, for CI gates
claude-review --pr owner/repo#123 --format json

# review a local diff, no network at all
claude-review --diff-file changes.diff --title "feat: something"

# use the model instead of the static analyzer
ANTHROPIC_API_KEY=sk-ant-xxx claude-review --pr owner/repo#123 --engine claude
```

## GitHub Action

`workflows/pr-review.yml` is a drop-in workflow: it checks out the reviewer, runs it on
`pull_request`, and comments on the PR. Copy it to `.github/workflows/` in the target repo
and set `REVIEWER_REPO`. Add an `ANTHROPIC_API_KEY` secret to switch engines; without it the
job runs the local analyzer for free.

## What the local engine actually catches

Measured on `samples/fixtures/bad-diff.diff` (a deliberately awful diff: leaked key, `.env`
committed, f-string SQL, `verify=False`, `shell=True`, `eval`, `except: pass`, three tests
deleted, lockfile without manifest) — every planted defect was reported, confidence `Low`:

```
🔴 Possible hardcoded credential committed            src/checkout.py:4
🔴 `.env` file modified in the change                 config/.env
🔴 SQL built by string interpolation                  src/checkout.py:8
🔴 TLS verification disabled                          src/checkout.py:10
🔴 `shell=True` turns interpolated input into command injection  src/checkout.py:13
🔴 `eval()` executes arbitrary strings                src/checkout.py:14
🟠 Exception handler swallows the error               src/checkout.py:11
🟠 Tests are net-shrinking here (−8/+2)               tests/test_checkout.py
🟠 Lockfile changed without its manifest              package-lock.json
```

## Tested on real PRs

Outputs in `samples/`, produced by the commands in this README — not mock-ups:

| PR | Size | Result |
|---|---|---|
| [openai/openai-python#4255](https://github.com/openai/openai-python/pull/4255) | 1 file, +3/−0 | `High` confidence, no risk |
| [openai/openai-python#4251](https://github.com/openai/openai-python/pull/4251) | 44 files, +394/−55 | `Medium`, flags the 449-line size and the security-sensitive paths |
| [claude-builders-bounty#5141](https://github.com/claude-builders-bounty/claude-builders-bounty/pull/5141) | 6 files, +338/−0 | `Medium`, flags the swallowed exception, credits the included tests |

The third one is a good sanity check: the reviewer credits the PR for shipping tests and
still finds the one real smell in it.

## Tests

```bash
cd agents/pr-reviewer
python -m unittest discover -s tests -v
```

27 tests, stdlib only: diff parsing (multi-file, line numbers, binaries), every detector
(secret, key, `shell=True`, `eval`, SQL interpolation, XSS sink, TLS off, swallowed
exception, `.env`, lockfile drift, schema change, test shrinking, binary, size→confidence),
docs-are-not-code scoping, the four required Markdown sections, the JSON shape, and ref parsing.

```
Ran 27 tests in 0.013s
OK
```

## Known limits — stated, not hidden

* Static analysis reads the diff, not the program: it cannot tell you the code is *correct*.
  `Confidence` is a review-depth estimate, not a correctness score.
* The `claude` engine is implemented and falls back gracefully, but this repository's
  test runs used the `local` engine (no API key on the machine that produced `samples/`).
  Run it with a key before trusting its output shape.
* `--comment` needs a token with `pull-requests: write`; without one it only prints.

## Layout

```
agents/pr-reviewer/
├── claude_review.py            # the reviewer (both engines)
├── claude-review               # bash entry point
├── claude-review.cmd           # Windows entry point
├── workflows/pr-review.yml     # drop-in GitHub Action
├── samples/                    # real PR outputs + one synthetic fixture
└── tests/test_review.py        # 27 stdlib tests
```
