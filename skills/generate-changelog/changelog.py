#!/usr/bin/env python3
"""
changelog.py — generate a structured CHANGELOG.md from git history.

    python changelog.py                     # commits since the last tag -> stdout
    python changelog.py --write             # ...-> prepend a section into CHANGELOG.md
    python changelog.py --since v1.2.0      # explicit range
    python changelog.py --repo owner/name   # add commit links
    python changelog.py --json              # machine-readable, for CI

Design notes
  * Commits since the most recent tag are grouped into Added / Fixed / Changed /
    Removed. The mapping is Conventional Commits first, keyword heuristic second,
    so repos that do not use the spec still produce something useful.
  * Docs / test / chore / ci / build / style commits are dropped by default:
    a changelog is for users, not for the maintainer's housekeeping.
    `--include-all` keeps them.
  * Writing is additive and idempotent per version: an existing section for the
    same version is replaced, never duplicated.
  * Zero dependencies, git is the only requirement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

CATEGORY_ORDER = ["Added", "Fixed", "Changed", "Removed"]

# Conventional Commit type -> category. None means "dropped unless --include-all".
TYPE_MAP = {
    "feat": "Added",
    "feature": "Added",
    "fix": "Fixed",
    "bugfix": "Fixed",
    "hotfix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "change": "Changed",
    "update": "Changed",
    "improve": "Changed",
    "remove": "Removed",
    "revert": "Removed",
    "deprecate": "Removed",
    "docs": None,
    "doc": None,
    "test": None,
    "tests": None,
    "chore": None,
    "ci": None,
    "build": None,
    "style": None,
    "deps": None,
    "release": None,
    "version": None,
    "v": None,
    "wip": None,
}

# Keyword fallback for repos without Conventional Commits.
KEYWORD_MAP: List[Tuple[str, str]] = [
    (r"\b(revert|remove[sd]?|delete[sd]?|drop(s|ped)?|deprecate[sd]?|kill)\b", "Removed"),
    (r"\b(fix(e[sd])?|bug|hotfix|patch|resolve[sd]?|correct(s|ed)?|repair)\b", "Fixed"),
    (r"\b(add(s|ed)?|new|introduce[sd]?|implement(s|ed)?|support(s|ed)?|allow(s|ed)?)\b", "Added"),
    (r"\b(refactor(s|ed)?|perf|optimi[sz]e[sd]?|improve[sd]?|change[sd]?|update[sd]?|"
     r"rename[sd]?|move[sd]?|bump|upgrade[sd]?|migrate[sd]?|clean(s|ed)?)\b", "Changed"),
]

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<subject>.+)$"
)
MERGE_RE = re.compile(r"^Merge (branch|pull request|remote-tracking branch|tag)\b", re.I)


# --------------------------------------------------------------------------- #
# git plumbing
# --------------------------------------------------------------------------- #
def git(*args: str, cwd: Optional[str] = None) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=cwd,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout.decode("utf-8", "replace")


def repo_root(cwd: Optional[str] = None) -> str:
    return git("rev-parse", "--show-toplevel", cwd=cwd).strip()


def latest_tag(cwd: Optional[str] = None) -> Optional[str]:
    """Most recent tag reachable from HEAD, preferring version-sorted names."""
    try:
        tags = git("tag", "--sort=-v:refname", "--merged", "HEAD", cwd=cwd).split()
    except RuntimeError:
        return None
    return tags[0] if tags else None


def head_ref(cwd: Optional[str] = None) -> str:
    try:
        return git("describe", "--tags", "--always", cwd=cwd).strip()
    except RuntimeError:
        return git("rev-parse", "--short", "HEAD", cwd=cwd).strip()


def read_commits(rev_range: str, cwd: Optional[str] = None) -> List[Dict[str, str]]:
    """Return [{hash, subject, body, author, date}] for the range."""
    sep, end = "\x1f", "\x1e"
    fmt = f"%H{sep}%s{sep}%b{sep}%an{sep}%aI{end}"
    raw = git("log", "--no-merges", f"--pretty=format:{fmt}", rev_range, cwd=cwd)
    commits: List[Dict[str, str]] = []
    for chunk in raw.split(end):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split(sep)
        if len(parts) < 5:
            continue
        commits.append({
            "hash": parts[0].strip(),
            "subject": parts[1].strip(),
            "body": parts[2].strip(),
            "author": parts[3].strip(),
            "date": parts[4].strip(),
        })
    return commits


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
def classify(subject: str, body: str = "") -> Optional[Tuple[str, str, bool]]:
    """(category, clean_subject, breaking) or None when the commit is dropped."""
    if MERGE_RE.match(subject):
        return None

    breaking = "BREAKING CHANGE" in body.upper() or "BREAKING-CHANGE" in body.upper()
    match = CONVENTIONAL_RE.match(subject)
    if match:
        ctype = match.group("type").lower()
        scope = match.group("scope")
        clean = match.group("subject").strip()
        breaking = breaking or bool(match.group("breaking"))
        category = TYPE_MAP.get(ctype, "Changed")
        if category is None:
            return None
        if scope:
            clean = f"**{scope}:** {clean}"
        return category, clean, breaking

    lowered = subject.lower()
    for pattern, category in KEYWORD_MAP:
        if re.search(pattern, lowered):
            return category, subject.strip(), breaking
    return None


def build_sections(
    commits: List[Dict[str, str]],
    repo: Optional[str] = None,
    include_all: bool = False,
) -> "OrderedDict[str, List[str]]":
    sections: "OrderedDict[str, List[str]]" = OrderedDict((c, []) for c in CATEGORY_ORDER)
    seen = set()
    for commit in commits:
        subject = commit["subject"]
        if not subject or subject in seen:
            continue
        result = classify(subject, commit.get("body", ""))
        if result is None:
            if not include_all:
                continue
            category, clean, breaking = "Changed", subject, False
        else:
            category, clean, breaking = result
        seen.add(subject)

        entry = clean.rstrip(".")
        if breaking:
            entry = f"**BREAKING** {entry}"
        short = commit["hash"][:7]
        if repo:
            entry = f"{entry} ([{short}](https://github.com/{repo}/commit/{commit['hash']}))"
        else:
            entry = f"{entry} ({short})"
        sections[category].append(entry)
    return OrderedDict((k, v) for k, v in sections.items() if v)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
HEADER = """# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
"""


def render_release(
    version: str,
    sections: "OrderedDict[str, List[str]]",
    date: str,
    compare_from: Optional[str] = None,
    compare_to: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    heading = f"## [{version}] - {date}"
    if repo and compare_from and compare_to:
        heading += f"\n\n[Full diff](https://github.com/{repo}/compare/{compare_from}...{compare_to})"
    lines = [heading, ""]
    if not sections:
        lines.append("_No user-facing changes._")
        lines.append("")
        return "\n".join(lines)
    for category, items in sections.items():
        lines.append(f"### {category}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


def merge_into_existing(existing: str, version: str, block: str) -> str:
    """Insert `block` right after the header, replacing an existing same-version section."""
    pattern = re.compile(
        r"^## \[" + re.escape(version) + r"\].*?(?=^## \[|\Z)", re.M | re.S
    )
    if pattern.search(existing):
        return pattern.sub(block.rstrip() + "\n\n", existing, count=1)

    marker = re.search(r"^## \[", existing, re.M)
    if marker:
        return existing[:marker.start()] + block.rstrip() + "\n\n" + existing[marker.start():]

    stripped = existing.rstrip()
    if not stripped:
        return HEADER + "\n" + block.rstrip() + "\n"
    return stripped + "\n\n" + block.rstrip() + "\n"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="changelog.py",
        description="Generate a structured CHANGELOG.md from git history.",
    )
    ap.add_argument("--since", help="git range or ref to start from (default: last tag)")
    ap.add_argument("--until", default="HEAD", help="end ref (default: HEAD)")
    ap.add_argument("--version", help="version label for the new section (default: tag or Unreleased)")
    ap.add_argument("--output", "-o", default="CHANGELOG.md", help="file to write with --write")
    ap.add_argument("--write", action="store_true", help="write into the changelog file instead of stdout")
    ap.add_argument("--repo", help="owner/name, used to build commit and compare links")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    ap.add_argument("--include-all", action="store_true", help="keep docs/test/chore/ci commits")
    ap.add_argument("--cwd", help="repository path (default: current directory)")
    args = ap.parse_args(argv)

    try:
        root = repo_root(args.cwd)
    except RuntimeError as exc:
        print(f"error: not a git repository ({exc})", file=sys.stderr)
        return 2

    tag = latest_tag(root)
    base = args.since or tag
    rev_range = f"{base}..{args.until}" if base else args.until

    # Commits *since* the last tag are by definition not part of that tag, so an
    # implicit run labels them [Unreleased] instead of reusing the tag name.
    if args.version:
        version = args.version
        compare_to = args.version.lstrip("v")
    elif args.since:
        version = head_ref(root)
        compare_to = version.lstrip("v")
    else:
        version = "Unreleased"
        compare_to = "HEAD"

    try:
        commits = read_commits(rev_range, cwd=root)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sections = build_sections(commits, repo=args.repo, include_all=args.include_all)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    compare_from = base.lstrip("v") if base else None

    if args.json:
        print(json.dumps({
            "version": version,
            "date": date,
            "range": rev_range,
            "previous": base,
            "commit_count": len(commits),
            "categories": {k: v for k, v in sections.items()},
        }, indent=2, ensure_ascii=False))
        return 0

    block = render_release(
        version, sections, date,
        compare_from=compare_from, compare_to=compare_to, repo=args.repo,
    )

    if not args.write:
        sys.stdout.write(block + "\n")
        return 0

    out_path = args.output if os.path.isabs(args.output) else os.path.join(root, args.output)
    existing = ""
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as fh:
            existing = fh.read()
    new_content = merge_into_existing(existing, version, block)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_content)
    os.replace(tmp, out_path)
    total = sum(len(v) for v in sections.values())
    print(
        f"wrote {out_path} — {total} entries under [{version}] "
        f"from {len(commits)} commits in {rev_range}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
