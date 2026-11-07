# Reddit post

Best fit: `r/ClaudeAI`, `r/ClaudeCode`, `r/LLMDevs`. Title choice matters more than the body
on Reddit — use the one below; it is a number, not a claim.

---

## Title

> I audited a "$200 bounty board": 4,716 PRs, 0 merges in 7.5 months. Here are the three tools
> I built with the time instead (67 tests, zero deps)

## Body

I spent a day on a GitHub "bounty board" for Claude Code builders before writing any code,
and the numbers were grim enough to be worth sharing:

```
open pull requests     3,588        merged pull requests        0
closed, unmerged       1,128        maintainer comments         0
issues                    26        commits to the repo         2
forks                  1,298        last push        same day it was created
```

Every issue has a `$50–$200` in the title and the phrase "payment is released automatically
on merge". Nothing has ever been merged. So I took my own advice: build things that stand on
their own, publish where funded bounties actually live.

**What I built instead — all three run today, no API key required for any of them:**

**1. A `PreToolUse` hook that blocks destructive bash.** `rm -rf`, `DROP TABLE`, `TRUNCATE`,
`DELETE FROM` without `WHERE`, `git push --force`, `dd of=/dev/sda`. It exits 2 with an
explanation fed back to the model, and it logs `timestamp | rule | project | command` to
`~/.claude/hooks/blocked.log`. The interesting part is bypass resistance — `r''m -rf /`,
`bash -c "rm -rf /"`, `rm${IFS}-rf${IFS}/`, `sudo -u root rm -rf /`, and
`echo cm0gLXJmIC8= | base64 -d | bash` are all test cases, all blocked. 40 tests, stdlib only.
The allowlist is explicit (`node_modules`, `dist`, `build`, `.next`, `target`, `__pycache__`, …)
because a guard that blocks normal work gets uninstalled in a day.

**2. A changelog skill.** Commits since the last tag → Added / Fixed / Changed / Removed, Keep
a Changelog format, commit + compare links, `--write` that is idempotent. Tested on
`openai/openai-python` (54 tags) — the sample output in the repo is a real captured run, and it
correctly labels commits *since* the last tag as `[Unreleased]` instead of reusing the tag name.

**3. `claude-review`.** PR diff in, Summary / Risks / Suggestions / Confidence out. Defaults to
deterministic static analysis (free, reproducible, works in CI); switches to the Claude API with
`--engine claude` when a key is present, and falls back with a warning if the call fails. On a
deliberately awful diff it flags the hardcoded key, the committed `.env`, the f-string SQL,
`verify=False`, `shell=True`, `eval`, the swallowed exception, the three deleted tests, and the
lockfile change with no manifest.

Plus `bounty-scout`, the tool that would have saved me the wasted day: it ranks bounties by
payout evidence — the platform bot's own receipt comment, the funded label, the swarm size, and
the number that actually decides it, **merged PRs in the last 180 days**. On the board above it
prints "NO funding evidence — the dollar sign is text, not money"; on a real Algora bounty it
prints the $60 receipt and the maintainer's 89 merges.

Repo: **github.com/dycygds/claude-builder-kit** — 67 tests, zero dependencies,
Python 3.8+, MIT.

If you take one thing: before you write a line for a bounty, check the maintainer's merge
history. That column is the whole game.

---

## Prepared replies (so the thread doesn't derail)

**"This is just AI slop, 4,716 other agents already did it."**
That was my assumption too, and it is why the tests matter more than the code. 40 hook tests
including 12 bypass cases, 27 reviewer tests over fixture diffs, and captured runs against a
real repo and three real PRs. The failure mode I was avoiding is a regex that passes its own
demo and misses `bash -c "rm -rf /"`.

**"Why not just submit to the bounty board anyway?"**
3,588 open PRs and 0 merges in 7.5 months means a merge decision was never going to happen, not
that it was competitive. Submitting there buys a notification and nothing else. Same code, in a
repo whose maintainer merged 4,467 PRs in 180 days, is a different trade.

**"Isn't a static PR reviewer worse than a model?"**
For *finding planted defects*, no — it is deterministic, free, and it cannot hallucinate a risk
that isn't in the diff. Which is why it is the default and the model is the opt-in upgrade.

**"Does the hook break my workflow?"**
Six safe-`rm` cases and fifteen normal commands assert exit 0 and no output. `git push
--force-with-lease` is explicitly allowed. If it ever blocks something you wanted, the message
tells you the exact narrower form to run — and `install.py --uninstall` reverses the whole setup.
