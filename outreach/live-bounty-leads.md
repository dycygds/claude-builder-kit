# Live bounty leads (captured 2026-11-07)

Produced by `python tools/bounty-scout/scout.py --limit 10 --enrich 10`, not by hand.
Full table: [`../tools/bounty-scout/live-bounties.md`](../tools/bounty-scout/live-bounties.md).

| score | amount | platform | issue | comments | merged PRs 180d | read |
|---:|---:|---|---|---:|---:|---|
| 14.29 | $60 | algora | [lablab-ai/community-content#462](https://github.com/lablab-ai/community-content/issues/462) | 32 | 89 | best risk/reward: small scoped doc work, active repo |
| 12.82 | $250 | algora | [onyx-dot-app/onyx#2281](https://github.com/onyx-dot-app/onyx/issues/2281) | 185 | **4467** | biggest amount in a repo that merges constantly — but 185 comments of competition |
| 7.50 | $600 | algora | [getdozer/dozer#1653](https://github.com/getdozer/dozer/issues/1653) | 30 | **0** | biggest number, worst odds: funded, frozen. Skip. |
| 5.56 | $600 | algora | [getdozer/dozer#1659](https://github.com/getdozer/dozer/issues/1659) | 44 | **0** | same repo, same problem |
| 1.01 | $250 | algora | [outerbase/starbasedb#71](https://github.com/outerbase/starbasedb/issues/71) | 114 | **0** | $250 of museum piece |

Two rows are the whole lesson: **$600 with 0 merges scores below $60 with 89 merges.** The
amount is decoration; the merge column is cash.

## Play 1 — onyx#2281 ($250, the only high-payout + high-merge combination)

```bash
python tools/bounty-scout/scout.py --verify onyx-dot-app/onyx#2281
```

If it prints `FUNDED and the maintainer merges`, post on the issue:

```
/attempt #2281
```

then immediately:

```
Plan:

- read `docs/` connector pattern for the existing Jira connector, mirror its file layout
- implement Jira Service Management as a separate connector class (do not fork the existing
  Jira one — they diverge on authentication)
- unit tests against a recorded fixture response; no network in CI
- docs page + one screenshot of the connector config UI

ETA: <N days>. If someone is already inside the auth layer, tell me and I will drop it.
```

## Play 2 — lablab-ai#462 ($60, the one with the least competition per dollar)

Small, scoped, writing-heavy. Ideal first submission: it proves the workflow (claim → PR →
merge → payout) with the smallest possible blast radius. Post `/attempt #462`, then the plan
comment, then a PR using the template in [`pr-description.md`](pr-description.md).

## What to skip, and why it matters that you skip it

`getdozer/dozer` has two $600 bounties and an archived project. The label says funded; the
merge history says the money cannot move. That is the same failure mode as the board this kit
was written for, just wearing a bigger number. Submitting there costs days and pays nothing.

## Before you claim anything

```bash
python tools/bounty-scout/scout.py --verify <owner/repo#N>     # funded? paying?
```

Three outcomes:

| verdict | meaning | action |
|---|---|---|
| `FUNDED and the maintainer merges` | receipt + active repo | claim it |
| `FUNDED but the maintainer has not merged in 6 months` | money exists, gate is shut | skip |
| `NO funding evidence` | the dollar sign is text | skip, do not even comment |
