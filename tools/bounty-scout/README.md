# bounty-scout

Rank GitHub bounties by **payout evidence** instead of by the dollar sign in the title.

Written after auditing a board with 4,716 PRs, 1,298 forks, a `$200` title — and **zero
merges in 7.5 months**, because money looks identical to bait until you check four things
this script checks for you.

## What it checks

| Signal | Why it decides everything |
|---|---|
| **payout bot** | The platform bot's own comment is the receipt. On Algora bounties the amount exists *only* there (`algora-pbc[bot]`: `## 💎 $60 bounty`). A human comment saying "opire" is never evidence — `/opire try` spam is what floods these threads. |
| **funded label** | `💎 Bounty` = Algora's label. A label is a claim; a label + a payout bot + a merging maintainer is funding. |
| **amount** | Bot comment first, then the title/body (`$75`, `75 USD`). Labelled `?` when nobody published it. |
| **competition** | Comment count, as a proxy for `/attempt` swarm size. |
| **maintainer** | **Merged PRs in the last 180 days.** This is the gate the other tools forget: a funded bounty pays nothing if nobody merges. |

Score = `amount / (1 + comments/10) × maintainer × freshness × funded`, where
`maintainer` collapses to `0.05` when the repo has merged nothing in six months. Every
weight is printed in `score()` — no hidden model.

## Usage

```bash
# rank the open Algora-funded issues
python scout.py --limit 10 --enrich 10

# write the shortlist out
python scout.py --limit 20 --markdown shortlist.md --json shortlist.json

# only bounties of $50 or more
python scout.py --min-amount 50

# is this one specific issue actually funded?
python scout.py --verify owner/repo#123
```

Set `GITHUB_TOKEN` to lift the anonymous rate limits (60 core / 10 search requests per
hour). Search quota exhaustion is reported as `?`, never silently as "no activity".

## The two controls, run live

Negative control — the board this tool was written for:

```
$ python scout.py --verify claude-builders-bounty/claude-builders-bounty#3
  labels          : bounty, hook, security
  funded label    : no
  payout bot      : none found
  amount          : $100
  comments        : 1914
  merged PRs 180d : 0
  verdict         : NO funding evidence — the dollar sign is text, not money
```

Positive control — a bounty with a receipt:

```
$ python scout.py --verify lablab-ai/community-content#462
  labels          : 💎 Bounty
  funded label    : YES -> 💎 Bounty
  payout bot      : algora
  amount          : $60 (from bot comment)
  comments        : 32
  merged PRs 180d : 89
  verdict         : FUNDED and the maintainer merges — this one can actually pay
```

`live-bounties.md` / `live-bounties.json` in this folder are a real captured scan.

## Why this exists

Bounty hunting fails in two ways, and both are invisible if you only read the issue:

1. **Unfunded bait** — the `$200` is text in a title. `/opire try` on it is a wasted week.
   Signal: no payout bot, no funded label, maintainer has merged nothing.
2. **Funded but frozen** — real money, but the maintainer stopped merging, so the reward
   can never be released. Signal: funded label present, `merged PRs 180d = 0`.

`bounty-scout` prints the four numbers that separate these from a bounty worth a weekend.

## Limits — stated, not hidden

* Amounts for some platforms live only on their dashboard; the script reports `?` rather
  than guessing.
* Comment count is a proxy for competing PRs, not a count of them: GitHub has no cheap
  linked-PR endpoint. When you shortlist a candidate, read the thread before writing code.
* Maintainer activity is measured over 180 days, so a repo that only merges twice a year
  scores near zero even if those merges are excellent — that is deliberate (a bounty is a
  cash-flow question, not a fairness question).
* `last update` is a weak signal and is treated as one: agent swarms bump `updated_at` every
  day on issues nobody has actually worked on. `merged PRs (180d)` is the column to trust.
