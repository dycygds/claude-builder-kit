# claude-builder-kit

Three production-grade Claude Code building blocks, plus one tool that tells you which
bounties are actually worth building them for.

Everything here was written and **executed on this machine**: 67 tests pass, every sample
in `samples/` is a captured run against real repositories and real pull requests. No mock-ups,
no "left as an exercise".

| Component | What it is | Status |
|---|---|---|
| [`hooks/block-destructive-bash`](hooks/block-destructive-bash/README.md) | `PreToolUse` hook that blocks `rm -rf`, `DROP TABLE`, `TRUNCATE`, `DELETE` without `WHERE`, `git push --force`, raw disk writes — and survives 12 denial-evasion techniques | 40/40 tests · `DEMO.txt` captured run |
| [`skills/generate-changelog`](skills/generate-changelog/README.md) | `CHANGELOG.md` generator: commits since the last tag → Added / Fixed / Changed / Removed | tested on `openai/openai-python` (54 tags) |
| [`agents/pr-reviewer`](agents/pr-reviewer/README.md) | `claude-review --pr <url>` → structured review comment (Summary / Risks / Suggestions / Confidence) + drop-in GitHub Action | 27/27 tests · 3 real PRs reviewed |
| [`tools/bounty-scout`](tools/bounty-scout/README.md) | Ranks bounties by payout evidence: payout-bot receipt, funded label, competition, maintainer merge rate | live scan captured: $2,145 across 10 issues |

## Why it exists

A "bounty board" with a `$200` title, 4,716 pull requests, 1,298 forks and **zero merges in
seven and a half months** is not a place to send code. Auditing it produced the numbers this
kit is built around:

```
open PRs          3,588        merged PRs            0
closed unmerged   1,128        maintainer comments   0
issues                26       commits               2
```

So the work went where it compounds instead: code that stands on its own, published where
funded bounties actually exist (Algora / Opire repos whose maintainers merge), with the
evidence attached to every claim.

## Quick start

```bash
git clone --depth 1 https://github.com/dycygds/claude-builder-kit
cd claude-builder-kit

# 1. install the destructive-command guard
python hooks/block-destructive-bash/install.py

# 2. try the changelog generator in any repo with tags
python skills/generate-changelog/changelog.py --repo owner/name

# 3. review a PR
python agents/pr-reviewer/claude_review.py --pr https://github.com/owner/repo/pull/123

# 4. find bounties that can actually pay
python tools/bounty-scout/scout.py --limit 10
```

Python 3.8+, no third-party packages anywhere in the repo.

## Ship it

The repo is committed locally and ready to publish. [`PUSH.md`](PUSH.md) documents the three
ways to authenticate (pre-filled token link, browser repo creation, or `gh auth login`), and
[`push.ps1`](push.ps1) does creation + topics + push in one command:

```powershell
$env:GITHUB_TOKEN = "ghp_..."      # scope: repo
powershell -ExecutionPolicy Bypass -File .\push.ps1
```

Then the launch material in [`outreach/`](outreach/) already points at the live URL.

## Verify the claims

```bash
cd hooks/block-destructive-bash && python -m unittest discover -s tests   # Ran 40 tests ... OK
cd agents/pr-reviewer           && python -m unittest discover -s tests   # Ran 27 tests ... OK
```

## Acceptance mapping

### HOOK — "pre-tool-use hook that blocks destructive bash commands" ($100)

| Requirement | Where |
|---|---|
| Claude Code hooks format (`~/.claude/hooks/`) | `install.py` copies to `~/.claude/hooks/block_destructive.py`, merges the `PreToolUse` entry; `--uninstall` reverses it |
| Blocks `rm -rf` | `rule_rm` — `rm -rf /`, `~/`, `/etc`, plus recursive-force anywhere outside an explicit build/cache allowlist |
| Blocks `DROP TABLE` | `rule_sql` → `sql_drop` |
| Blocks `TRUNCATE` | `rule_sql` → `sql_truncate` |
| Blocks `DELETE FROM` without `WHERE` | `rule_sql` → `sql_delete_without_where`, per statement, SQL-context aware |
| Blocks `git push --force` | `rule_git_push` (`--force-with-lease` deliberately allowed) |
| Logs timestamp + command + project path | `log_block()` → `~/.claude/hooks/blocked.log`, verified by `Logging` tests, real file in `DEMO.txt` |
| Clear message telling Claude why | exit `2` + stderr explanation with rule, offending token and the fix; `--json` emits `permissionDecision: deny` |
| Does not interfere with normal commands | 15 normal commands + 6 safe `rm -rf` cases assert exit `0` and silence |
| README, install in ≤2 commands | `git clone … && python …/install.py`, then restart Claude Code |

### SKILL — "generate a structured CHANGELOG from git history" ($50)

| Requirement | Where |
|---|---|
| Works via `/generate-changelog` or `bash changelog.sh` | `commands/generate-changelog.md` + `changelog.sh` (both verified in this session) |
| Commits since last tag | `latest_tag()` uses `--sort=-v:refname --merged HEAD` |
| Auto-categories Added/Fixed/Changed/Removed | `TYPE_MAP` (Conventional Commits) + `KEYWORD_MAP` fallback |
| Properly formatted `CHANGELOG.md` | Keep a Changelog sections, compare links, commit links, idempotent merge |
| Tested on a real repo, sample in the PR | `sample-output/` — real run on `openai/openai-python`, 54 tags |
| README, setup in ≤3 steps | 3 steps in `skills/generate-changelog/README.md` |

### AGENT — "PR reviewer with structured Markdown output" ($150)

| Requirement | Where |
|---|---|
| CLI: `claude-review --pr <url>` | `claude-review` / `claude-review.cmd` wrappers |
| Or GitHub Action | `workflows/pr-review.yml` |
| Summary (2–3 sentences) | rendered by `render_markdown()` |
| Risks list | `review_locally()` — 20 detectors |
| Improvement suggestions | same |
| Confidence Low/Medium/High | `score`-based confidence, asserted by tests |
| Tested on ≥2 real PRs, outputs in the PR | 3 real PRs in `samples/` (`openai/openai-python#4255`, `#4251`, `claude-builders-bounty#5141`) |
| README with setup and usage | `agents/pr-reviewer/README.md` |

## Where the money actually is

`tools/bounty-scout` scans for payout receipts instead of titles. A real captured run:

```
| score | amount | platform | issue                                                        | comments | merged 180d |
|------:|-------:|----------|--------------------------------------------------------------|---------:|------------:|
| 14.29 |    $60 | algora   | lablab-ai/community-content#462                               |       32 |          89 |
| 12.82 |   $250 | algora   | onyx-dot-app/onyx#2281                                        |      185 |        4467 |
|  7.50 |   $600 | algora   | getdozer/dozer#1653                                           |       30 |           0 |
```

The `merged 180d` column is the one that matters: a funded bounty in a repo that merges
nothing is a museum piece. Negative control from the board this kit was written for:

```
$ python scout.py --verify claude-builders-bounty/claude-builders-bounty#3
  funded label    : no
  payout bot      : none found
  merged PRs 180d : 0
  verdict         : NO funding evidence — the dollar sign is text, not money
```

## Layout

```
claude-builder-kit/
├── hooks/block-destructive-bash/    # PreToolUse guard + installer + 40 tests + DEMO.txt
├── skills/generate-changelog/       # generator + SKILL.md + slash command + real sample
├── agents/pr-reviewer/              # CLI, GitHub Action, 27 tests, 3 real PR reviews
├── tools/bounty-scout/              # payout-evidence scanner + live scan output
└── outreach/                        # launch posts + PR & claim comment templates
```

## License

MIT.
