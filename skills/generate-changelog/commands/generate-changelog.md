---
description: Generate a structured CHANGELOG.md from git history (Added/Fixed/Changed/Removed)
allowed-tools: Bash, Read, Write, Edit
---

Generate a changelog section for this repository.

1. Preview the section, scoped to the last tag, with commit links:

   ```bash
   python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/skills/generate-changelog/changelog.py" --repo "$(git config --get remote.origin.url | sed -E 's#.*[:/]([^/]+/[^/.]+)(\.git)?$#\1#')"
   ```

   If the user passed a range or version (`/generate-changelog v1.4.0`, `/generate-changelog since v1.3.0`),
   forward it as `--since <ref>` / `--version <label>`.

2. Show the preview to the user. Do not write files yet.
3. If they approve, run the same command with `--write` to prepend the section into
   `CHANGELOG.md`, then `git diff --stat CHANGELOG.md`.
4. Summarise: commits scanned, entries per category, version heading used.

Rules: never fabricate entries, never reorder categories, keep `**BREAKING**` markers.
