### Hi, I'm dycygds 👋

I build small, tested tools for AI agents — the kind that prevent damage instead of describing it.

---

#### 🧰 Featured: [claude-builder-kit](https://github.com/dycygds/claude-builder-kit)

A guard, a changelog generator and a PR reviewer for Claude Code — plus the tool that tells you
which bounties can actually pay. **67 tests · zero dependencies · Python 3.8+ · MIT**

| | |
|---|---|
| 🛡️ | **`PreToolUse` guard** — blocks `rm -rf`, `DROP TABLE`, `TRUNCATE`, `DELETE` without `WHERE`, `git push --force`, raw disk writes. Survives 12 evasion techniques (`r''m -rf /`, `bash -c`, `base64 \| bash`, `${IFS}`, `sudo -u root`, …). 40 tests. |
| 📝 | **changelog generator** — commits since the last tag → Added / Fixed / Changed / Removed, with commit and compare links. Verified on `openai/openai-python` (54 tags); `--write` is idempotent. |
| 🔍 | **`claude-review`** — PR diff → Summary / Risks / Suggestions / Confidence. Runs with **no API key** (deterministic static analysis), upgrades to the Claude API when you have one. 27 tests, 3 real PRs reviewed. |
| 💰 | **`bounty-scout`** — ranks bounties by payout evidence (platform bot receipt, funded label, swarm size) and by the metric that decides it: has this maintainer merged anything in 180 days? |

```bash
git clone https://github.com/dycygds/claude-builder-kit
python claude-builder-kit/hooks/block-destructive-bash/install.py   # restart Claude Code after
```

---

<sub>Every number in that repo is a captured run against a real repository or a real pull request — not a mock-up.</sub>
