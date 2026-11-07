#!/usr/bin/env python3
"""
Install (or remove) the block-destructive-bash hook for Claude Code.

    python install.py            # install: copy hook + merge ~/.claude/settings.json
    python install.py --uninstall
    python install.py --dry-run

What it touches (nothing else):
  ~/.claude/hooks/block_destructive.py      (created / replaced)
  ~/.claude/settings.json                   (one PreToolUse entry merged in)

Safety:
  * settings.json is backed up to settings.json.bak.<UTC timestamp> before the
    first write, and the exact restore command is printed at the end.
  * merge is idempotent: running it twice does not duplicate the entry.
  * a malformed existing settings.json aborts instead of being overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOK_SRC = Path(__file__).resolve().parent / "block_destructive.py"
HOOK_NAME = "block_destructive.py"
HOOK_MARKER = "block_destructive.py"


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def python_cmd(hook_path: Path) -> str:
    """Command string Claude Code will execute."""
    exe = "python3" if os.name != "nt" else "python"
    return f'{exe} "{hook_path.as_posix()}"'


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"refusing to touch {path}: not valid JSON ({exc}).\n"
            f"Fix or move it, then re-run."
        )
    if not isinstance(data, dict):
        raise SystemExit(f"refusing to touch {path}: expected a JSON object at the top level.")
    return data


def already_installed(settings: dict) -> bool:
    pre = settings.get("hooks", {}).get("PreToolUse", [])
    if not isinstance(pre, list):
        return False
    for entry in pre:
        for hook in (entry or {}).get("hooks", []) or []:
            if HOOK_MARKER in str(hook.get("command", "")):
                return True
    return False


def merge_entry(settings: dict, command: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre, list):
        raise SystemExit("hooks.PreToolUse in ~/.claude/settings.json is not a list; aborting.")
    for entry in pre:
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher") == "Bash":
            entry.setdefault("hooks", [])
            if any(HOOK_MARKER in str(h.get("command", "")) for h in entry["hooks"]):
                return settings
            entry["hooks"].append({"type": "command", "command": command, "timeout": 10})
            return settings
    pre.append({
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": command, "timeout": 10}],
    })
    return settings


def uninstall_entry(settings: dict) -> dict:
    pre = settings.get("hooks", {}).get("PreToolUse", [])
    if not isinstance(pre, list):
        return settings
    kept = []
    for entry in pre:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        entry["hooks"] = [
            h for h in entry.get("hooks", []) or []
            if HOOK_MARKER not in str((h or {}).get("command", ""))
        ]
        if entry.get("hooks") or not entry.get("matcher") == "Bash":
            kept.append(entry)
    settings["hooks"]["PreToolUse"] = kept
    return settings


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Install the Claude Code destructive-command hook.")
    ap.add_argument("--uninstall", action="store_true", help="remove the hook and its settings entry")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = ap.parse_args(argv)

    root = claude_dir()
    hooks_dir = root / "hooks"
    hook_dst = hooks_dir / HOOK_NAME
    settings_path = root / "settings.json"

    if not HOOK_SRC.exists():
        print(f"error: {HOOK_SRC} not found — run this from the hook directory.", file=sys.stderr)
        return 1

    settings = load_settings(settings_path)
    command = python_cmd(hook_dst)

    if args.uninstall:
        if not args.dry_run:
            uninstall_entry(settings)
            write_atomic(settings_path, json.dumps(settings, indent=2) + "\n")
            if hook_dst.exists():
                hook_dst.unlink()
        print(f"[uninstall] removed hook from {settings_path}")
        print(f"[uninstall] deleted {hook_dst}" if not args.dry_run else "[dry-run] nothing written")
        return 0

    action = "no-op (already installed)" if already_installed(settings) else "install"

    print(f"[{action}] hook   -> {hook_dst}")
    print(f"[{action}] entry  -> {settings_path}")
    print(f"[{action}] command: {command}")

    if args.dry_run:
        print("[dry-run] nothing written")
        return 0

    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SRC, hook_dst)

    backup = None
    if settings_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = settings_path.with_name(f"settings.json.bak.{stamp}")
        shutil.copy2(settings_path, backup)

    merge_entry(settings, command)
    write_atomic(settings_path, json.dumps(settings, indent=2) + "\n")

    # self-check: re-read what we just wrote
    verify = json.loads(settings_path.read_text(encoding="utf-8"))
    ok = already_installed(verify)

    print()
    print("verified: hook entry present in settings.json" if ok else "WARNING: verification failed")
    if backup:
        print(f"backup:   {backup}")
        print(f"rollback: copy \"{backup}\" over \"{settings_path}\" and delete \"{hook_dst}\"")
    else:
        print(f"rollback: delete \"{hook_dst}\" and remove the PreToolUse/Bash entry from \"{settings_path}\"")
    print()
    print("Next: restart Claude Code, then try `rm -rf /` in a Bash tool call.")
    print(f"Blocks are logged to {Path.home() / '.claude' / 'hooks' / 'blocked.log'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
