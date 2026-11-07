# PR description + claim comments

Two artefacts per bounty issue:

1. a **claim comment** posted first (on Algora: `/attempt #<n>`; on Opire: `/opire try`), and
2. a **PR body** built from the template below, with the acceptance checklist transcribed and
   each box tied to a file or a command.

The second part is what wins review. Do not describe the work — cite it.

---

## 1. Claim comment

### Algora-funded issue (`💎 Bounty` label, `algora-pbc[bot]` comment present)

```
/attempt #<NUMBER>
```

Then, in the same thread, post the plan so a human can see intent before the PR lands:

```
Plan for this one:

- <one line per acceptance bullet, in the order the issue lists them>
- tests: <what I will add and how a reviewer can run it in one command>
- evidence: the PR body will carry captured command output, not screenshots of intent

ETA: <hours/days>. If someone is deeper in already, say so and I will drop it — no hard feelings.
```

### Opire-funded issue

```
/opire try
```

Only worth posting after `python tools/bounty-scout/scout.py --verify <owner/repo#N>` returns
`FUNDED and the maintainer merges`. On a repo with `merged PRs 180d = 0`, skip it entirely.

---

## 2. PR body template

```markdown
## What this does

<2-3 sentences. What it is, where it lives, what a user types.>

## Acceptance criteria

- [x] <copy the issue bullet verbatim> — `<path/to/file.py:LINE>`
- [x] <next bullet> — `<path>`
- [x] Tested on a real repo — output in `<samples/FILE>`, produced by `<exact command>`
- [x] README, setup in ≤N steps — `<README.md>`

## Proof

<details><summary>Test run (copy-pasted, not retyped)</summary>

```
$ python -m unittest discover -s tests
Ran 40 tests in 6.219s
OK
```

</details>

<details><summary>Real run</summary>

```
$ <the exact command a reviewer would run>
<its actual output>
```

</details>

## Design decisions worth arguing about

- **<decision>** — <why, and what the alternative would have cost>. If you want the other
  behaviour, it is one constant: `<path:LINE>`.
- **<second decision>** — <why>.

## What I deliberately did not do

- <scope you cut, and the reason. This is the section that makes a reviewer trust the rest.>

## How to try it

```bash
<2-4 commands, copy-pasteable, ending in something visible happening>
```

## Rollback

<exact command or file to delete. Required for anything that writes to a machine.>
```

---

## 3. Per-bounty fill-in (for the three issues in `claude-builder-kit`)

### HOOK — destructive command guard

| Issue bullet | Evidence to cite |
|---|---|
| hooks format | `install.py` writes `~/.claude/hooks/block_destructive.py` and merges the `PreToolUse` entry; `settings.example.json` for hand-installs |
| blocks the 5 patterns | `block_destructive.py` → `rule_rm`, `rule_sql`, `rule_git_push`; tests `RequiredPatterns` |
| logs timestamp/command/path | `log_block()`; real file contents quoted in `DEMO.txt` |
| clear message to Claude | exit 2 + stderr block; `Protocol.test_json_decision_mode` covers the JSON form |
| no interference | `NoFalsePositives` — 15 normal commands, 6 safe `rm -rf` cases |
| README ≤2 commands | `git clone … && python hooks/block-destructive-bash/install.py` |

Design decisions to flag in the PR body: **fail-open** (a crashing hook must never brick a
session), the **build/cache allowlist** (a guard that blocks `rm -rf ./node_modules` gets
uninstalled in a day), and **`--force-with-lease` deliberately allowed**.

### SKILL — changelog generator

| Issue bullet | Evidence to cite |
|---|---|
| `/generate-changelog` or `bash changelog.sh` | `commands/generate-changelog.md`, `changelog.sh` |
| since last tag | `latest_tag()` — `git tag --sort=-v:refname --merged HEAD` |
| four categories | `TYPE_MAP` + `KEYWORD_MAP`; `sample-output/CHANGELOG.sample.md` |
| formatted output | Keep a Changelog sections + compare and commit links |
| tested on a real repo | `sample-output/RUN.txt` — `openai/openai-python`, 54 tags |
| README ≤3 steps | 3 numbered steps |

### AGENT — PR reviewer

| Issue bullet | Evidence to cite |
|---|---|
| CLI | `claude-review --pr <url>` (`claude-review`, `claude-review.cmd`) |
| GitHub Action | `workflows/pr-review.yml` |
| structured output | four fixed sections in `render_markdown()` |
| ≥2 real PRs, outputs included | `samples/` — `openai/openai-python#4255`, `#4251`, `claude-builders-bounty#5141` |
| README | setup, usage, Action, limits |

---

## 4. Follow-up comment after submitting

```
Submitted: <PR link>

Two things a reviewer usually asks:

1. "How do I know it works?" — `python -m unittest discover -s tests` from the component
   directory; every claim in the PR body is a command in that suite.
2. "What is the blast radius?" — <one sentence: files touched, anything that writes to disk,
   and the rollback command>.

Happy to adjust the design decisions in the "worth arguing about" section — those are
preferences, not load-bearing.
```
