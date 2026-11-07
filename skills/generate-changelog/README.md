# generate-changelog

Turn `git log` into a `CHANGELOG.md` a user can actually read: commits grouped into
**Added / Fixed / Changed / Removed**, scoped to the last tag, formatted per
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Works two ways, both required by the issue: as a Claude Code skill (`/generate-changelog`)
and as a plain script (`bash changelog.sh`).

## Setup — 3 steps

1. Copy the folder into your project or your global skills dir:

   ```bash
   cp -r generate-changelog ~/.claude/skills/          # skill mode
   # or: cp generate-changelog/changelog.sh ./ && chmod +x changelog.sh   # script mode
   ```

2. Preview the next release (no files touched):

   ```bash
   bash changelog.sh --repo owner/name
   ```

3. Write it when the preview looks right:

   ```bash
   bash changelog.sh --repo owner/name --write
   ```

No dependencies. Python 3.8+ and `git`.

## How commits are classified

| Category | Conventional types | Keyword fallback |
|---|---|---|
| `Added` | `feat`, `feature` | add, new, introduce, implement, support, allow |
| `Fixed` | `fix`, `bugfix`, `hotfix` | fix, bug, patch, resolve, correct, repair |
| `Changed` | `perf`, `refactor`, `change`, `update`, `improve` | refactor, optimise, improve, update, rename, bump, migrate |
| `Removed` | `remove`, `revert`, `deprecate` | remove, delete, drop, deprecate, kill |
| *dropped* | `docs`, `test`, `chore`, `ci`, `build`, `style`, `deps`, `release` | — |

Conventional Commits win; the keyword map is there so repos that never adopted the spec
still get a sensible result. `--include-all` keeps the housekeeping commits.
A `!` in the type (`feat!:`) or a `BREAKING CHANGE:` footer prefixes the bullet with
`**BREAKING**`.

## Options

```
--since REF          start of the range (default: most recent tag)
--until REF          end of the range (default: HEAD)
--version LABEL      heading for the new section (default: Unreleased)
--write              prepend into CHANGELOG.md instead of printing
--output, -o FILE    target file for --write (default: CHANGELOG.md)
--repo OWNER/NAME    add commit links and a compare link
--json               machine-readable output for CI
--include-all        keep docs/test/chore/ci commits
--cwd PATH           repository path
```

## Guarantees

* **Additive and idempotent.** Running `--write` twice does not duplicate a section; an
  existing section for the same version is replaced in place and every other release
  section in the file is left untouched (verified against
  `openai/openai-python`, whose `CHANGELOG.md` already had 54 release entries).
* **Nothing invented.** Every bullet maps 1:1 to a real commit hash that is embedded in
  the output.
* **Tagless repos work.** No tag reachable from `HEAD` ⇒ the section is `[Unreleased]`
  and the whole history is scanned.

## Tested on a real repository

`sample-output/CHANGELOG.sample.md` and `sample-output/RUN.txt` are captured runs against
[`openai/openai-python`](https://github.com/openai/openai-python) — a real project with 54
tags and Conventional Commits:

```bash
$ python3 changelog.py --repo openai/openai-python
## [Unreleased] - 2026-11-07

[Full diff](https://github.com/openai/openai-python/compare/3.47.0...HEAD)

### Added

- **api:** add stream options for agent sessions (#4251) ([c6fc264](https://github.com/openai/openai-python/commit/c6fc264...))
```

Also verified on a tagless repository (the output correctly falls back to a single
`[Unreleased]` section over the full history), and through the `bash changelog.sh`
wrapper on Windows + Git Bash (the `python3` Microsoft Store stub is probed and skipped
in favour of a working interpreter).

## Layout

```
generate-changelog/
├── changelog.py                    # the generator
├── changelog.sh                    # bash entry point (issue requirement)
├── SKILL.md                        # Claude Code skill definition
├── commands/generate-changelog.md  # /generate-changelog slash command
└── sample-output/                  # real runs, not mock-ups
```
