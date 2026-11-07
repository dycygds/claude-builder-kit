# X / Twitter thread

Ready to post — every link points at `github.com/dycygds/claude-builder-kit`. Post as 7 tweets
in one thread. Attach a screenshot of `DEMO.txt` (the block message) to tweet 2 — it is the most
scroll-stopping asset in the kit.

Each tweet below is under 280 characters (measured: 241 / 205 / 236 / 246 / 221 / 238 / 208).

---

**1/**

I audited a "$200 bounty board" on GitHub.

4,716 PRs. 1,298 forks. 0 merges in 7.5 months. The maintainer has never left a single comment.

So I stopped chasing the prize and built things that survive on their own. 🧵

---

**2/**

First: a Claude Code hook that blocks what an agent should never run.

rm -rf / · DROP TABLE · DELETE FROM with no WHERE · git push --force · dd of=/dev/sda

Exit 2, with the reason fed back to the model.

[attach DEMO.txt screenshot]

---

**3/**

The part everyone gets wrong: a regex on the raw string is not a guard.

r''m -rf /
bash -c "rm -rf /"
rm${IFS}-rf${IFS}/
sudo -u root rm -rf /
echo cm0gLXJmIC8= | base64 -d | bash

12 of these. 12 unit tests. 12 blocked.

---

**4/**

Then a changelog skill that works on real repos.

Tested on openai/openai-python (54 tags): commits since the last tag → Added / Fixed /
Changed / Removed, with commit and compare links.

--write is idempotent: re-running never duplicates a section.

---

**5/**

Then claude-review: PR diff in → Summary / Risks / Suggestions / Confidence out.

No API key needed — deterministic static analysis. Upgrade to the model with --engine claude.

3 real PRs reviewed, outputs committed in the repo.

---

**6/**

Then the one I use daily: bounty-scout.

It ranks bounties by payout evidence, not by the number in the title — and by the metric that
decides everything: has this maintainer merged anything in 180 days?

The $200 board: 0 merges. Skip.

---

**7/**

67 tests. Zero dependencies. Python 3.8+.

The audit numbers, the live bounty scan, and all three tools:

github.com/dycygds/claude-builder-kit

If you build with agents, install the guard today. The rest is taste.

---

## Reply bait (post as a self-reply, so it shows in the thread and in search)

The hook's allowlist is deliberate: `rm -rf ./node_modules` and `rm -rf dist` pass without
prompting. A guard that blocks normal work gets uninstalled in a day — so what should be on
that list that I missed?

## Hashtags

`#ClaudeCode #AIAgents #DevTools #OpenSource`

## Before you hit post

- [ ] tweet 2 has the `DEMO.txt` screenshot attached (the blocked-message block, not a terminal
      full of scrolling output)
- [ ] tweet 7 link opens the repo in a logged-out window — check it once in incognito
- [ ] post the reply bait as your own reply, not as tweet 8
- [ ] pin the thread to your profile afterwards (X: "Pin to profile" from the ⋯ menu)
