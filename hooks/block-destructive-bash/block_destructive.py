#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — blocks destructive bash / SQL commands.

Contract (Claude Code hooks):
  stdin  : JSON  {"session_id", "transcript_path", "cwd", "hook_event_name",
                  "tool_name": "Bash", "tool_input": {"command": "...", ...}}
  deny   : exit code 2 + explanation on stderr  (stderr is fed back to Claude)
  allow  : exit code 0

Design rules
  1. FAIL OPEN. Any internal error -> exit 0. A guard that bricks the agent is
     worse than a guard that misses one command.
  2. Normalise before matching. Quotes, backslashes, nested shells (bash -c,
     eval), `xargs`, and base64 payloads are unwrapped first, because
     `r''m -rf /` is the same command as `rm -rf /`.
  3. Allow what is provably safe. `rm -rf ./node_modules` is normal work;
     `rm -rf /` is not. The allowlist is explicit and printed by `--selftest`.
  4. Every block is logged with timestamp + attempt + project path.

Zero third-party dependencies. Python 3.8+.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Tuple

VERSION = "1.0.0"

DEFAULT_LOG = os.path.join("~", ".claude", "hooks", "blocked.log")
MAX_DEPTH = 3

# Directories that are safe to wipe with `rm -rf` when given as a RELATIVE path.
SAFE_RM_DIRS = {
    "node_modules", "dist", "build", "out", ".next", ".nuxt", ".turbo", ".svelte-kit",
    "target", "bin", "obj", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "coverage", ".coverage", ".cache", "tmp", ".tmp", ".venv", "venv", ".parcel-cache",
    ".gradle", ".idea-out", ".nyc_output", "storybook-static", "playwright-report",
}

# Paths whose recursive deletion is always a disaster.
CRITICAL_TARGETS = {
    "/", "/*", "~", "~/", "$HOME", "${HOME}", "/etc", "/usr", "/var", "/bin", "/sbin",
    "/boot", "/lib", "/lib64", "/opt", "/srv", "/root", "/home", "/Users", "/System",
    "/Applications", "/Volumes", "C:\\", "C:/", "D:\\", "D:/", "\\", "//",
    ".", "..", "./", "../",
}

SQL_CLIENTS = {
    "psql", "mysql", "mariadb", "sqlite3", "sqlite", "duckdb", "clickhouse-client",
    "sqlcmd", "usql", "pgcli", "mycli", "psql.exe", "mysql.exe", "sqlite3.exe",
}

SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "ash", "busybox-sh", "pwsh", "powershell"}

PREFIX_WRAPPERS = {"sudo", "doas", "nohup", "time", "env", "command", "builtin",
                   "exec", "nice", "ionice", "stdbuf", "unbuffer", "busybox", "chroot",
                   "timeout", "watch", "xargs", "systemd-run"}

SQL_KEYWORDS = ("DROP", "TRUNCATE", "DELETE", "ALTER", "GRANT", "REVOKE", "UPDATE")


# --------------------------------------------------------------------------- #
# payload
# --------------------------------------------------------------------------- #
def read_payload(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def extract_command(payload: dict) -> Tuple[str, str]:
    """Return (command, project_dir) from a hook payload."""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    cmd = tool_input.get("command") or tool_input.get("cmd") or ""
    if not isinstance(cmd, str):
        cmd = str(cmd)
    cwd = payload.get("cwd") or os.getcwd()
    return cmd, str(cwd)


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #
def mask_quoted_args(text: str) -> str:
    """Blank out quoted *arguments* so text that merely mentions a dangerous
    command is not executed in the matcher.

        echo "rm -rf / is banned"   ->  echo QARG
        r''m -rf /                  ->  rm -rf /        (quotes are interior)

    A quoted run is treated as an argument only when (a) it is not in command
    position and (b) it contains whitespace. `"rm" -rf /` therefore still reads
    as `rm -rf /`, because a one-word quoted token can be an executable.
    """
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch not in "'\"":
            out.append(ch)
            i += 1
            continue
        j = text.find(ch, i + 1)
        if j == -1:
            i += 1
            continue
        inner = text[i + 1:j]
        before = text[i - 1] if i > 0 else ""
        after = text[j + 1] if j + 1 < n else ""
        at_boundary_before = (i == 0) or before in " \t\n;&|()"
        at_boundary_after = (j + 1 >= n) or after in " \t\n;&|()"
        command_position = at_boundary_before and before == ""
        if at_boundary_before and at_boundary_after and not command_position and " " in inner.strip():
            out.append("QARG")
        else:
            out.append(inner)
        i = j + 1
    return "".join(out)


def deobfuscate(text: str) -> str:
    """Strip shell quoting/escaping noise so `r''m -\\rf /` becomes `rm -rf /`."""
    out = re.sub(r"\\(?=[^\s])", "", text)          # \rm -> rm ; -\-force -> --force
    out = out.replace("'", "").replace('"', "")      # r''m -> rm
    out = out.replace("${IFS}", " ").replace("$IFS", " ")
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def split_segments(command: str) -> List[str]:
    """Split a shell line into independently executed sub-commands.

    Quote aware: `psql -c 'DELETE FROM t; DELETE FROM u;'` stays one segment,
    while `cd /tmp && rm -rf /` becomes two. Splitting inside quotes used to
    hide the SQL payload, which is exactly how the first version missed it.
    """
    segments: List[str] = []
    buf: List[str] = []
    depth = 0
    quote = ""          # "", "'", '"'
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            elif ch == "\\" and quote == '"' and i + 1 < n:
                i += 1
                buf.append(command[i])
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ";|&\n":
            segments.append("".join(buf))
            buf = []
            if command[i:i + 2] in ("&&", "||"):
                i += 1
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s for s in (seg.strip() for seg in segments) if s]


def tokenize(segment: str) -> List[str]:
    try:
        return shlex.split(segment, posix=True)
    except Exception:
        return segment.split()


def strip_wrappers(tokens: Sequence[str]) -> List[str]:
    """Drop env assignments / sudo / nohup / timeout 5 ... to find the real argv[0]."""
    toks = list(tokens)
    while toks:
        head = toks[0]
        base = os.path.basename(head).lower()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):     # FOO=bar cmd
            toks.pop(0)
            continue
        if base in PREFIX_WRAPPERS:
            toks.pop(0)
            # `timeout 30 cmd`, `nice -n 5 cmd`
            while toks and (re.match(r"^-", toks[0]) or re.match(r"^\d+[smhd]?$", toks[0])):
                toks.pop(0)
            continue
        break
    return toks


def shell_bodies(segment: str) -> List[str]:
    """Extract the script handed to an inner shell: bash -c '...', eval '...', xargs rm."""
    bodies: List[str] = []
    for m in re.finditer(
        r"(?:^|[\s;&|])(?:bash|sh|zsh|dash|ksh|ash|pwsh|powershell)\b[^;|&\n]*?\s-[a-zA-Z]*c[a-zA-Z]*\s+"
        r"(\"[^\"]*\"|'[^']*'|\S+)",
        segment,
    ):
        body = m.group(1)
        if body[:1] in "'\"":
            body = body[1:-1]
        bodies.append(body)
    for m in re.finditer(r"(?:^|[\s;&|])eval\s+(\"[^\"]*\"|'[^']*'|\S+)", segment):
        body = m.group(1)
        if body[:1] in "'\"":
            body = body[1:-1]
        bodies.append(body)
    return bodies


DECODED_COMMAND_RE = re.compile(
    r"\b(rm|git|dd|mkfs|mke2fs|shred|sh|bash|zsh|eval|psql|mysql|sqlite3|"
    r"drop|delete|truncate|curl|wget|chmod|chown)\b",
    re.I,
)


def base64_payloads(segment: str) -> List[str]:
    """Catch `echo cm0gLXJmIC8= | base64 -d | bash`.

    Only runs when the segment actually mentions an encoder or pipes into a
    shell, so a 40-char git SHA in a normal command is never decoded.
    """
    if not (
        re.search(r"\b(base64|base32|atob|frombase64)\b", segment, re.I)
        or re.search(r"\|\s*(bash|sh|zsh|dash|ksh)\b", segment)
    ):
        return []
    found: List[str] = []
    for m in re.finditer(r"\b([A-Za-z0-9+/]{8,}={0,2})\b", segment):
        blob = m.group(1)
        try:
            decoded = base64.b64decode(
                blob + "=" * (-len(blob) % 4), validate=True
            ).decode("utf-8", "ignore")
        except Exception:
            continue
        if not decoded.strip():
            continue
        if not all(c.isprintable() or c in "\r\n\t" for c in decoded):
            continue
        if DECODED_COMMAND_RE.search(decoded):
            found.append(decoded)
    return found


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
class Finding:
    __slots__ = ("rule", "reason", "detail")

    def __init__(self, rule: str, reason: str, detail: str = ""):
        self.rule = rule
        self.reason = reason
        self.detail = detail


def _flag_tokens(args: Sequence[str]) -> Tuple[set, List[str]]:
    """Return (short flag letters, long flags) from an argv tail."""
    shorts = set()
    longs = set()
    for a in args:
        if a.startswith("--"):
            longs.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1 and a != "-":
            for ch in a[1:]:
                shorts.add(ch)
    return shorts, longs


def _non_flags(args: Sequence[str]) -> List[str]:
    out = []
    for a in args:
        if a == "--":
            continue
        if a.startswith("-") and a != "-":
            continue
        out.append(a)
    return out


def _is_safe_rm_target(target: str) -> bool:
    t = target.strip()
    if not t or t.startswith("/") or t.startswith("~") or t.startswith("$"):
        return False
    if ".." in t.split("/") or t.startswith(".."):
        return False
    if any(ch in t for ch in "*?[]"):
        return False
    parts = [p for p in re.split(r"[\\/]+", t) if p]
    if not parts:
        return False
    return parts[-1] in SAFE_RM_DIRS and len(parts) <= 2


def rule_rm(argv: Sequence[str]) -> Optional[Finding]:
    """rm with recursive+force, --no-preserve-root, or a critical target."""
    if not argv:
        return None
    base = os.path.basename(argv[0]).lower()
    if base not in ("rm", "rm.exe"):
        return None
    args = list(argv[1:])
    shorts, longs = _flag_tokens(args)
    targets = _non_flags(args)

    recursive = "r" in shorts or "R" in shorts or "--recursive" in longs
    force = "f" in shorts or "--force" in longs
    no_preserve = "--no-preserve-root" in longs
    critical = [t for t in targets if t in CRITICAL_TARGETS or t.startswith("~/") or t == "$HOME"]
    wildcard = [t for t in targets if any(ch in t for ch in "*?") and t.rstrip("/") in ("/", "/*", "*")]

    if no_preserve:
        return Finding("rm_no_preserve_root",
                       "`rm --no-preserve-root` explicitly disables the guard that protects `/`.",
                       ", ".join(targets))
    if critical and (recursive or no_preserve):
        return Finding("rm_critical_path",
                       "Recursive delete of a system/home/root path can destroy the OS or every "
                       "uncommitted file you have.",
                       ", ".join(critical))
    if wildcard:
        return Finding("rm_wildcard_root",
                       "Recursive delete with a wildcard rooted at `/` deletes system files.",
                       ", ".join(wildcard))
    if recursive and force:
        unsafe = [t for t in targets if not _is_safe_rm_target(t)]
        if unsafe or not targets:
            return Finding(
                "rm_recursive_force",
                "`rm -rf` deletes recursively AND without prompting, so a typo cannot be undone. "
                "Allowed without confirmation only for build/cache dirs "
                "(node_modules, dist, build, .next, target, __pycache__, ...).",
                ", ".join(unsafe) if unsafe else "(no target)",
            )
    return None


def _sql_context(argv: Sequence[str], segment: str) -> bool:
    """True when the command actually runs SQL (not just mentions it)."""
    if argv:
        base = os.path.basename(argv[0]).lower()
        if base in SQL_CLIENTS:
            return True
        if base in ("python", "python3", "node", "ruby", "php"):
            return False
    if re.search(r"\b(sqlite3|psql|mysql)\b", segment):
        return True
    if re.search(r"\.sql\b", segment):
        return True
    if re.match(r"^\s*(delete\s+from|drop\s+table|drop\s+database|truncate)\b", segment, re.I):
        return True
    return False


def _sql_statements(text: str) -> List[str]:
    parts = re.split(r";|\n", text)
    return [p.strip() for p in parts if p.strip()]


SQL_PAYLOAD_FLAGS = {"-c", "-e", "--command", "--execute", "--query", "-q", "-Q"}


def _sql_payload(argv: Sequence[str], segment: str) -> str:
    """Everything the SQL client is actually asked to run."""
    if argv:
        for i, a in enumerate(list(argv)[1:], start=1):
            for flag in SQL_PAYLOAD_FLAGS:
                if a == flag:
                    return " ".join(argv[i + 1:])
                if a.startswith(flag + "="):
                    return a.split("=", 1)[1]
    return segment


def rule_sql(argv: Sequence[str], segment: str) -> Optional[Finding]:
    if not _sql_context(argv, segment):
        return None
    payload = _sql_payload(argv, segment)
    normalised = deobfuscate(payload)
    for stmt in _sql_statements(normalised):
        upper = stmt.upper()
        if re.search(r"\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)\b", upper):
            return Finding("sql_drop",
                           "`DROP TABLE/DATABASE` is irreversible and takes the data with it.",
                           stmt[:160])
        if re.search(r"\bTRUNCATE\b", upper):
            return Finding("sql_truncate",
                           "`TRUNCATE` empties a table in place with no rollback in most engines.",
                           stmt[:160])
        if re.search(r"\bDELETE\s+FROM\b", upper) and not re.search(r"\bWHERE\b", upper):
            return Finding("sql_delete_without_where",
                           "`DELETE FROM` without a `WHERE` clause deletes every row in the table. "
                           "Add a WHERE clause, or use a transaction you can roll back.",
                           stmt[:160])
    return None


def rule_git_push(argv: Sequence[str]) -> Optional[Finding]:
    if not argv or os.path.basename(argv[0]).lower() not in ("git", "git.exe"):
        return None
    args = list(argv[1:])
    # skip git global options: -C dir, -c k=v, --git-dir=..., --no-pager
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c", "--git-dir", "--work-tree"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        break
    if i >= len(args) or args[i].lower() != "push":
        return None
    rest = args[i + 1:]
    shorts, longs = _flag_tokens(rest)
    if "--force-with-lease" in longs:
        return None
    if "--force" in longs or "f" in shorts or "--mirror" in longs:
        return Finding(
            "git_push_force",
            "A forced push rewrites remote history and can erase commits that other people "
            "already based work on. Use `--force-with-lease`, which refuses when the remote "
            "moved under you.",
            " ".join(argv[:6]),
        )
    return None


def rule_disk_destroy(argv: Sequence[str], segment: str) -> Optional[Finding]:
    if argv:
        base = os.path.basename(argv[0]).lower()
        if base in ("mkfs", "mkfs.ext4", "mke2fs", "wipefs", "shred", "fdisk", "parted", "diskpart"):
            return Finding("disk_destroy",
                           f"`{base}` writes directly to a block device and destroys the filesystem.",
                           " ".join(argv[:6]))
        if base == "dd":
            for a in argv[1:]:
                if a.startswith("of=/dev/") or a.startswith("of=\\\\.\\"):
                    return Finding("disk_destroy", "`dd of=/dev/...` overwrites a raw disk device.",
                                   a)
    if re.search(r">\s*/dev/(sd|nvme|hd|vd|disk)", segment):
        return Finding("disk_destroy", "Redirecting output onto a raw block device wipes the disk.",
                       segment[:120])
    return None


def rule_fork_bomb(segment: str) -> Optional[Finding]:
    if re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", segment.replace(" ", "")):
        return Finding("fork_bomb", "Fork bomb: exhausts process table and locks the machine.",
                       segment[:80])
    return None


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
WATCHED_EXECS = {
    "rm", "git", "dd", "mkfs", "mke2fs", "wipefs", "shred", "fdisk", "parted", "diskpart",
    "psql", "mysql", "mariadb", "sqlite3", "duckdb", "clickhouse-client", "sqlcmd", "usql",
    "pgcli", "mycli",
}


def exec_slices(tokens: Sequence[str]) -> List[List[str]]:
    """Every plausible argv inside the segment.

    `sudo -u root rm -rf /` and `timeout 30 rm -rf /` put a wrapper's option
    value in front of the real command, so we also slice from any token whose
    basename is a command we care about. Cheap, and it closes the whole class
    of prefix bypasses rather than the two we happened to test.
    """
    slices: List[List[str]] = []
    stripped = strip_wrappers(tokens)
    if stripped:
        slices.append(stripped)
    for i, tok in enumerate(tokens):
        base = os.path.basename(tok).lower()
        if base in WATCHED_EXECS and i > 0:
            slices.append(list(tokens[i:]))
    return slices


def analyse(command: str, depth: int = 0) -> List[Finding]:
    """Return every finding for a command string (recurses into nested shells)."""
    findings: List[Finding] = []
    if depth > MAX_DEPTH:
        return findings

    # Decode `... | base64 -d | bash` across the whole line: the blob and the
    # decoder live in different pipeline segments, so per-segment scanning
    # never sees both halves.
    for decoded in base64_payloads(command):
        findings.extend(analyse(decoded, depth + 1))

    for segment in split_segments(command):
        normalised = deobfuscate(mask_quoted_args(segment))
        candidates = [segment] if normalised == segment else [segment, normalised]
        for candidate in candidates:
            for argv in exec_slices(tokenize(candidate)):
                for rule in (
                    lambda a, s: rule_rm(a),
                    lambda a, s: rule_sql(a, candidate),
                    lambda a, s: rule_git_push(a),
                    lambda a, s: rule_disk_destroy(a, candidate),
                    lambda a, s: rule_fork_bomb(candidate),
                ):
                    try:
                        hit = rule(argv, candidate)
                    except Exception:
                        hit = None
                    if hit:
                        findings.append(hit)

        for body in shell_bodies(segment):
            findings.extend(analyse(body, depth + 1))

        # `find / -delete` and `find ... -exec rm`
        if re.search(r"\bfind\b.*(-delete|-exec\s+rm|-exec\s+/bin/rm)", deobfuscate(segment)):
            findings.append(Finding(
                "find_delete",
                "`find ... -delete` / `-exec rm` deletes recursively based on a pattern; a wrong "
                "path deletes far more than intended.",
                segment[:140]))

    # dedupe, keep first per rule
    seen = set()
    unique: List[Finding] = []
    for f in findings:
        key = (f.rule, f.detail)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


# --------------------------------------------------------------------------- #
# logging / reporting
# --------------------------------------------------------------------------- #
def log_path() -> str:
    return os.path.expanduser(os.environ.get("BLOCK_DESTRUCTIVE_LOG") or DEFAULT_LOG)


def log_block(finding: Finding, command: str, project_dir: str) -> str:
    path = log_path()
    line = " | ".join(
        [
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "BLOCKED",
            f"rule={finding.rule}",
            f"project={project_dir}",
            f"command={json.dumps(command, ensure_ascii=False)}",
        ]
    )
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    return path


def format_message(findings: Sequence[Finding], command: str, project_dir: str, path: str) -> str:
    lines = [
        "",
        "BLOCKED by block-destructive-bash (Claude Code PreToolUse hook)",
        "=" * 62,
        "Command: " + (command[:400] + ("..." if len(command) > 400 else "")),
        "Project: " + project_dir,
        "",
    ]
    for f in findings:
        lines.append(f"- [{f.rule}] {f.reason}")
        if f.detail:
            lines.append(f"  offending: {f.detail}")
    lines += [
        "",
        "What to do instead:",
        "  * narrow the target (e.g. `rm -rf ./dist`, not `rm -rf /`)",
        "  * add a WHERE clause, or wrap the delete in a transaction",
        "  * use `git push --force-with-lease` instead of `--force`",
        "  * if this really is intended, run it yourself in a terminal;",
        "    the agent is intentionally not allowed to do it unattended.",
        "",
        f"Logged to: {path}",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def selftest() -> int:
    samples = [
        ("rm -rf /", True),
        ("rm -rf ./node_modules", False),
        ("git push --force origin main", True),
        ("git push --force-with-lease origin main", False),
        ("psql -c 'DELETE FROM users'", True),
        ("psql -c 'DELETE FROM users WHERE id = 1'", False),
        ("npm run build", False),
        ('bash -c "rm -rf /"', True),
        ("echo cm0gLXJmIC8= | base64 -d | bash", True),
    ]
    bad = 0
    for cmd, expect_block in samples:
        got = bool(analyse(cmd))
        flag = "ok " if got == expect_block else "FAIL"
        if got != expect_block:
            bad += 1
        print(f"[{flag}] expect_block={expect_block!s:5} got={got!s:5} :: {cmd}")
    print(f"\nsafe rm allowlist: {', '.join(sorted(SAFE_RM_DIRS))}")
    print(f"log file: {log_path()}")
    return 0 if bad == 0 else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv:
        print(f"block-destructive {VERSION}")
        return 0
    if "--selftest" in argv:
        return selftest()

    try:
        payload = read_payload(sys.stdin.read())
    except Exception:
        return 0  # fail open

    try:
        command, project_dir = extract_command(payload)
        if not command.strip():
            return 0
        findings = analyse(command)
        if not findings:
            return 0
        path = log_block(findings[0], command, project_dir)
        message = format_message(findings, command, project_dir, path)

        if "--json" in argv:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                }
            }, ensure_ascii=False))
        sys.stderr.write(message + "\n")
        return 2
    except Exception:
        return 0  # fail open on any bug


if __name__ == "__main__":
    sys.exit(main())
