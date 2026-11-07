# X / Twitter thread

Ready to post — every link already points at `github.com/dycygds/claude-builder-kit`, so
nothing needs editing once the repo is pushed. Post as 6 tweets in one
thread. Attach a screenshot of `DEMO.txt` (the block message) to tweet 2 — it is the most
scroll-stopping asset in the kit.

---

**1/**

I audited a "$200 bounty board" on GitHub.

4,716 pull requests. 1,298 forks. **0 merges in 7.5 months.** The maintainer has never
posted a single comment.

So I stopped competing for the prize and built things that survive on their own. 🧵

---

**2/**

First: a Claude Code hook that blocks the commands an agent should never run.

`rm -rf /`, `DROP TABLE`, `DELETE FROM` with no `WHERE`, `git push --force`, `dd of=/dev/sda`.

Exit 2 + an explanation fed back to the model, so it learns *why* instead of retrying.
[attach DEMO.txt screenshot]

---

**3/**

The part everyone gets wrong: a regex on the raw command string is not a guard.

`r''m -rf /`
`bash -c "rm -rf /"`
`rm${IFS}-rf${IFS}/`
`sudo -u root rm -rf /`
`echo cm0gLXJmIC8= | base64 -d | bash`

All 12 of these are unit tests. All 12 are blocked.

---

**4/**

Then a changelog skill that works on real repos, not demos.

Tested on `openai/openai-python` — 54 tags, Conventional Commits — commits since the last tag
grouped into Added / Fixed / Changed / Removed, with commit + compare links, `--write`
idempotent so a re-run never duplicates a section.

---

**5/**

Then `claude-review`: PR diff → Summary / Risks / Suggestions / Confidence.

Runs with **no API key** (deterministic static analysis), upgrades to the Claude API when you
have one. 3 real PRs reviewed, outputs committed. On a planted-bad diff it catches the leaked
key, the f-string SQL, `shell=True`, `verify=False`, `eval`, and the deleted tests.

---

**6/**

And the tool I actually use daily: `bounty-scout`.

It ranks bounties by *payout evidence* — the platform bot's receipt, the funded label, the
swarm size, and the number that decides everything: **has this maintainer merged anything in
180 days?**

The $200 board: 0 merges. Verdict: the dollar sign is text, not money.

---

**7/**

67 tests. Zero dependencies. Python 3.8+.

Everything here, including the audit numbers and the live bounty scan, is in one repo:
github.com/dycygds/claude-builder-kit

If you're building with agents: the guard is the one to install today. The rest is taste.

---

## Reply bait (post as a self-reply so it shows in the thread and in search)

The hook's allowlist is deliberate: `rm -rf ./node_modules` and `rm -rf dist` pass without
prompting. A guard that blocks normal work gets uninstalled in a day — so what should be on
that list that I missed?

## Hashtags

`#ClaudeCode #AIAgents #DevTools #OpenSource`
