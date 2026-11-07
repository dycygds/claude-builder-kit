# block-destructive-bash

A Claude Code `PreToolUse` hook that stops the agent **before** it runs a command that
cannot be undone: `rm -rf`, `DROP TABLE`, `TRUNCATE`, `DELETE FROM` without `WHERE`,
`git push --force`, raw disk writes.

Single file. Zero dependencies. Python 3.8+.

---

## Install (2 commands)

```bash
git clone --depth 1 https://github.com/dycygds/claude-builder-kit
python claude-builder-kit/hooks/block-destructive-bash/install.py
```

That is the whole setup. `install.py` copies the hook to `~/.claude/hooks/block_destructive.py`
and merges one `PreToolUse` entry into `~/.claude/settings.json` (backing it up first, and
skipping the merge if it is already there). Restart Claude Code and the guard is live.

Prefer to do it by hand? Copy `settings.example.json`'s block into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/hooks/block_destructive.py\"", "timeout": 10 }] }
    ]
  }
}
```

## What it blocks

| Rule | Trigger | Example |
|---|---|---|
| `rm_critical_path` | recursive delete of `/`, `~`, `/etc`, `C:\`, ... | `rm -rf /`, `rm -rf ~/` |
| `rm_recursive_force` | `rm -rf` on anything that is not a build/cache dir | `rm -rf src` |
| `rm_no_preserve_root` | the flag that exists only to defeat this guard | `rm -rf --no-preserve-root /` |
| `rm_wildcard_root` | `rm -rf /*` | `rm -rf /*` |
| `sql_drop` | `DROP TABLE / DATABASE` | `psql -c 'DROP TABLE users'` |
| `sql_truncate` | `TRUNCATE` | `psql -c 'TRUNCATE orders'` |
| `sql_delete_without_where` | `DELETE FROM` with no `WHERE` in the same statement | `psql -c 'DELETE FROM users'` |
| `git_push_force` | `git push --force` / `-f` / `--mirror` | `git push -f origin main` |
| `disk_destroy` | `dd of=/dev/…`, `mkfs`, `> /dev/sda` | `dd if=/dev/zero of=/dev/sda` |
| `find_delete` | `find … -delete`, `find … -exec rm` | `find / -delete` |
| `fork_bomb` | `:(){ :|:& };:` | — |

## What it deliberately does **not** block

A guard that blocks normal work gets uninstalled in a day, so the allowlist is explicit:

* `rm -rf ./node_modules`, `dist`, `build`, `out`, `.next`, `.turbo`, `target`, `__pycache__`,
  `.pytest_cache`, `coverage`, `tmp`, `.venv`, … — full list in `block_destructive.py:SAFE_RM_DIRS`
* `git push --force-with-lease` — the safe version of the force push
* `DELETE FROM t WHERE id = 42`
* anything that only *mentions* a dangerous command:
  `git commit -m "docs: explain why DROP TABLE is dangerous"`, `grep -rn 'DELETE FROM' migrations/`,
  `echo "rm -rf is banned here" >> NOTES.md`

## Bypass resistance

Most "block rm -rf" hooks are a regex on the raw string. These are the same command wearing a
disguise, and every one of them is a test case:

| Bypass | Why the naive regex misses it | Handled by |
|---|---|---|
| `r''m -rf /` | quote split breaks the literal `rm` | quote-aware de-obfuscation |
| `\rm -rf /` | backslash escape | escape stripping |
| `rm${IFS}-rf${IFS}/` | `${IFS}` instead of a space | `$IFS` normalisation |
| `bash -c "rm -rf /"` | command is in an argument | recursive inner-shell analysis |
| `eval 'rm -rf /'` | idem | recursive `eval` analysis |
| `sudo rm -rf /etc` | wrapper prefix | wrapper stripping + exec slicing |
| `FOO=1 sudo -u root rm -rf /` | option *value* sits in front of `rm` | exec slicing: analyse from any watched binary |
| `cd /tmp && rm -rf /` | second segment | quote-aware segment splitting |
| `find src \| xargs rm -rf` | argv built by xargs | wrapper stripping |
| `echo cm0gLXJmIC8= \| base64 -d \| bash` | payload is encoded | base64 decoding across the pipeline |
| `psql -c 'SELECT 1; DELETE FROM t;'` | second statement | per-statement SQL parsing |
| `find / -delete` | no `rm` at all | dedicated rule |

## Log

Every block appends one line to `~/.claude/hooks/blocked.log` (override with
`BLOCK_DESTRUCTIVE_LOG`):

```
2026-11-07T10:31:27Z | BLOCKED | rule=rm_critical_path | project=/project/payments | command="rm -rf /"
```

Timestamp (UTC), rule, project path, attempted command — the four fields you need to audit what
the agent tried to do. Logging failures are swallowed; they never block your session.

## Failure modes, on purpose

* **Fail open.** Unparseable stdin, missing `tool_input`, or any internal exception ⇒ exit `0`.
  A guard that bricks the agent is worse than a guard that misses one command.
* **Exit `2` + stderr** is the deny path: Claude Code feeds that text back to the model, so the
  agent is told *why* it was stopped and what to do instead. `--json` emits the equivalent
  `permissionDecision: deny` payload if you prefer the JSON protocol.

## Tests

40 tests, stdlib only — no pytest needed:

```bash
cd hooks/block-destructive-bash
python -m unittest discover -s tests -v
```

Real run on this machine (Python 3.12.10, Windows):

```
Ran 40 tests in 6.219s
OK
```

Coverage: 5 required pattern families, 15 normal commands that must **not** fire, 6 safe
`rm -rf` cases, 12 bypass cases, the logging contract, and the fail-open protocol.
`DEMO.txt` is a captured end-to-end run: exit codes, the message Claude receives, and the
resulting log file.

## Uninstall

```bash
python install.py --uninstall
```

Or delete `~/.claude/hooks/block_destructive.py` and the `PreToolUse`/`Bash` entry in
`~/.claude/settings.json`. `install.py` prints the exact rollback command after every install.
