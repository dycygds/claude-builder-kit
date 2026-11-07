---
name: generate-changelog
description: Generate a structured CHANGELOG.md (Keep a Changelog format) from git history, grouped into Added / Fixed / Changed / Removed. Use when the user asks for a changelog, release notes, "what changed since the last release", or to prepare a release.
---

# Generate a changelog from git history

Produce a `CHANGELOG.md` section describing every user-facing change since the
previous release, categorised the way Keep a Changelog expects.

## When to use

Trigger on: "generate a changelog", "release notes", "what changed since v1.4.0",
"prep the next release", "summarise this sprint for users".

Do **not** use it for internal refactor diaries — that is what `git log` is for.

## Steps

1. Confirm you are inside a git repository (`git rev-parse --show-toplevel`).
2. Preview first, never blind-write:

   ```bash
   python3 changelog.py --repo owner/name
   ```

   Add `--since <tag>` when the user names a range; the default is
   "everything since the most recent tag".
3. Read the preview. Sanity-check the categories:
   * `Added` — new features (`feat:`, "add", "introduce")
   * `Fixed` — bug fixes (`fix:`, "resolve", "correct")
   * `Changed` — behaviour/perf/refactor (`perf:`, "refactor", "update")
   * `Removed` — deletions and reverts (`remove`, `drop`, "revert")
   * docs/test/chore/ci/build are dropped on purpose — pass `--include-all` only if the
     user explicitly wants maintainer housekeeping in the log.
4. Write it:

   ```bash
   python3 changelog.py --repo owner/name --write
   ```

   The writer is additive and idempotent: an existing section for the same version is
   replaced in place, never duplicated, and unrelated sections are left untouched.
5. Report to the user: how many commits were scanned, how many entries landed in each
   category, and which version heading was used.

## Output shape

```markdown
## [v1.2.0] - 2026-11-07

[Full diff](https://github.com/owner/name/compare/v1.1.0...v1.2.0)

### Added
- **client:** support streaming responses ([a1b2c3d](https://github.com/owner/name/commit/...))

### Fixed
- **retry:** do not retry 4xx responses ([e4f5g6h](...))
```

## Rules

* Never invent commits. Every bullet must come from `git log`.
* Never edit categories by hand to look nicer; if the classification is wrong, fix the
  commit subject or improve `KEYWORD_MAP` in `changelog.py`.
* Mark breaking changes: a `!` in the type (`feat!:`) or a `BREAKING CHANGE:` footer
  prefixes the bullet with `**BREAKING**`.
* No repository tags yet? The version heading becomes `[Unreleased]` — say so instead of
  inventing a version number.
