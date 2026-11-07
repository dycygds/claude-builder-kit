#!/usr/bin/env python3
"""
claude-review — review a GitHub pull request and emit a structured Markdown comment.

    claude-review --pr https://github.com/owner/repo/pull/123
    claude-review --pr owner/repo#123 --out review.md
    claude-review --pr owner/repo#123 --comment          # post it (needs GITHUB_TOKEN)
    claude-review --diff-file changes.diff --title "feat: x"   # offline / CI

Output is always the same four sections, which is what makes it safe to drop into a
GitHub Action or a PR timeline:

    Summary of changes (2-3 sentences)
    Identified risks (list)
    Improvement suggestions (list)
    Confidence score: Low | Medium | High

Two engines:
  * local  (default)  deterministic static analysis of the diff — no API key, no network
                       beyond fetching the PR, reproducible, runs in CI for free.
  * claude (--engine claude) sends the diff to the Anthropic API, falls back to local
                       analysis if the call fails, and says so in the output.

Zero third-party dependencies. Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

VERSION = "1.0.0"
API_ROOT = "https://api.github.com"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_DIFF_CHARS = 120_000


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass
class FileDiff:
    path: str
    added: int = 0
    removed: int = 0
    added_lines: List[Tuple[int, str]] = field(default_factory=list)
    removed_lines: List[Tuple[int, str]] = field(default_factory=list)
    is_binary: bool = False


@dataclass
class PullRequest:
    owner: str
    repo: str
    number: int
    title: str = ""
    author: str = ""
    body: str = ""
    base: str = ""
    head: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    diff: str = ""
    files: List[FileDiff] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"

    @property
    def total_lines(self) -> int:
        return sum(f.added + f.removed for f in self.files) or (self.additions + self.deletions)


@dataclass
class Finding:
    severity: str          # "high" | "medium" | "low"
    message: str
    location: str = ""

    def render(self) -> str:
        icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(self.severity, "•")
        where = f" `{self.location}`" if self.location else ""
        return f"- {icon} {self.message}{where}"


@dataclass
class Review:
    summary: str
    risks: List[Finding]
    suggestions: List[str]
    confidence: str
    engine: str = "local"


# --------------------------------------------------------------------------- #
# diff parsing
# --------------------------------------------------------------------------- #
def parse_diff(diff: str) -> List[FileDiff]:
    files: List[FileDiff] = []
    current: Optional[FileDiff] = None
    new_line = 0
    old_line = 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            match = re.search(r" b/(.+)$", raw)
            current = FileDiff(path=match.group(1) if match else raw[11:])
            files.append(current)
            continue
        if current is None:
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            current.is_binary = True
            continue
        if raw.startswith("--- ") or raw.startswith("+++ ") or raw.startswith("index "):
            continue
        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if raw.startswith("+"):
            current.added += 1
            current.added_lines.append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-"):
            current.removed += 1
            current.removed_lines.append((old_line, raw[1:]))
            old_line += 1
        else:
            new_line += 1
            old_line += 1
    return files


TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test\.|\.test\.|\.spec\.|Test\.java$)", re.I)
SOURCE_EXT_RE = re.compile(
    r"\.(py|js|jsx|ts|tsx|go|rs|java|kt|rb|php|cs|c|cc|cpp|h|hpp|swift|m|scala|sh|sql|vue|svelte)$", re.I
)
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "uv.lock", "requirements.lock",
}
MANIFESTS = {
    "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod",
    "composer.json", "Gemfile", "setup.py", "setup.cfg",
}

SECRET_PATTERNS: Sequence[Tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "private key material"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API secret key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token|auth[_-]?token)\b"
                r"\s*[:=]\s*[\"'][^\"']{8,}[\"']"), "hardcoded credential"),
]

CODE_PATTERNS: Sequence[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\beval\s*\("), "high", "`eval()` executes arbitrary strings"),
    (re.compile(r"\bexec\s*\("), "high", "`exec()` executes arbitrary strings"),
    (re.compile(r"new Function\s*\("), "high", "`new Function` is eval in disguise"),
    (re.compile(r"pickle\.loads?\s*\("), "high", "`pickle` deserialisation of untrusted data is RCE"),
    (re.compile(r"yaml\.load\s*\((?![^)]*Loader)"), "high", "`yaml.load` without a safe Loader is RCE"),
    (re.compile(r"shell\s*=\s*True"), "high", "`shell=True` turns interpolated input into command injection"),
    (re.compile(r"os\.system\s*\("), "high", "`os.system` passes the string to a shell"),
    (re.compile(r"\bexecute\s*\(\s*[f\"'].*(?:\+|\{).*"), "high", "SQL built by string interpolation"),
    (re.compile(r"innerHTML\s*="), "high", "`innerHTML` assignment is an XSS sink"),
    (re.compile(r"dangerouslySetInnerHTML"), "high", "`dangerouslySetInnerHTML` bypasses React escaping"),
    (re.compile(r"\bv-html\b"), "high", "`v-html` renders unescaped HTML"),
    (re.compile(r"verify\s*=\s*False"), "high", "TLS verification disabled"),
    (re.compile(r"rejectUnauthorized\s*:\s*false"), "high", "TLS verification disabled"),
    (re.compile(r"InsecureSkipVerify\s*:\s*true"), "high", "TLS verification disabled"),
    (re.compile(r"except\s*:\s*pass\b"), "medium", "bare `except: pass` hides every failure"),
    (re.compile(r"except\s+Exception\s*:\s*pass\b"), "medium", "swallowed exception (`except Exception: pass`)"),
    (re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"), "medium", "empty catch block swallows errors"),
    (re.compile(r"\bdebugger\b\s*;?"), "low", "leftover `debugger` statement"),
    (re.compile(r"(?i)\b(TODO|FIXME|XXX|HACK)\b"), "low", "new TODO/FIXME marker"),
    (re.compile(r"\bconsole\.(log|debug)\s*\("), "low", "console logging left in the change"),
    (re.compile(r"\bprint\s*\("), "low", "`print()` debug output left in the change"),
]

SENSITIVE_PATH_RE = re.compile(r"(auth|oauth|crypto|payment|billing|security|session|token|password|admin)", re.I)


# --------------------------------------------------------------------------- #
# local reviewer
# --------------------------------------------------------------------------- #
def _classify(files: Sequence[FileDiff]) -> Dict[str, List[FileDiff]]:
    groups = {"test": [], "source": [], "docs": [], "ci": [], "lock": [], "manifest": [],
              "migration": [], "env": [], "binary": [], "config": [], "other": []}
    for f in files:
        path = f.path
        lower = path.lower()
        base = os.path.basename(lower)
        if TEST_PATH_RE.search(path):
            groups["test"].append(f)
        elif f.is_binary:
            groups["binary"].append(f)
        elif base.startswith(".env") or lower.endswith(".env.example"):
            groups["env"].append(f)
        elif base in LOCKFILES:
            groups["lock"].append(f)
        elif base in MANIFESTS:
            groups["manifest"].append(f)
        elif lower.startswith(".github/workflows/") or base in (".gitlab-ci.yml", "Jenkinsfile"):
            groups["ci"].append(f)
        elif "migration" in lower or lower.endswith(".sql"):
            groups["migration"].append(f)
        elif lower.endswith((".md", ".mdx", ".rst", ".txt")) or base in ("license", "notice"):
            groups["docs"].append(f)
        elif SOURCE_EXT_RE.search(path):
            groups["source"].append(f)
        elif lower.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf")):
            groups["config"].append(f)
        else:
            groups["other"].append(f)
    return groups


def _swallowed_exceptions(f: FileDiff) -> List[Finding]:
    """Multi-line scan: an empty handler is only visible across two lines."""
    findings: List[Finding] = []
    lines = [(n, t.strip()) for n, t in f.added_lines if t.strip()]
    for i, (lineno, text) in enumerate(lines):
        if re.match(r"^except\b.*:\s*$", text) or re.match(r"^catch\s*\(.*\)\s*\{\s*$", text):
            nxt = lines[i + 1][1] if i + 1 < len(lines) else ""
            if nxt in ("pass", "}", "{}", "return", "continue"):
                findings.append(Finding(
                    "medium",
                    "Exception handler swallows the error — the failure becomes invisible",
                    f"{f.path}:{lineno}",
                ))
    return findings


def review_locally(pr: PullRequest) -> Review:
    groups = _classify(pr.files)
    risks: List[Finding] = []
    suggestions: List[str] = []

    # 1. secret material
    for f in pr.files:
        for lineno, text in f.added_lines:
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(text):
                    risks.append(Finding("high", f"Possible {label} committed", f"{f.path}:{lineno}"))
                    break
        if f.path.split("/")[-1].startswith(".env") and not f.path.endswith(".example"):
            risks.append(Finding("high", "`.env` file modified in the change", f.path))

    # 2. dangerous code patterns — source and SQL only. Scanning READMEs and test
    #    fixtures for `print(` produces exactly the noise that gets a reviewer muted.
    seen_rules: Dict[str, int] = {}
    for f in list(groups["source"]) + list(groups["migration"]):
        for lineno, text in f.added_lines:
            stripped = text.strip()
            if not stripped:
                continue
            for pattern, severity, message in CODE_PATTERNS:
                if pattern.search(stripped):
                    seen_rules[message] = seen_rules.get(message, 0) + 1
                    if seen_rules[message] <= 3:
                        risks.append(Finding(severity, message, f"{f.path}:{lineno}"))

    for f in list(groups["source"]) + list(groups["migration"]):
        risks.extend(_swallowed_exceptions(f))

    # 3. tests
    if groups["source"] and not groups["test"]:
        suggestions.append(
            f"No test changes accompany {len(groups['source'])} modified source file(s) — "
            "add a regression test or explain why none applies."
        )
    for f in groups["test"]:
        if f.removed > f.added:
            risks.append(Finding(
                "medium",
                f"Tests are net-shrinking here (−{f.removed}/+{f.added}) — check nothing is being skipped",
                f.path,
            ))

    # 4. dependency drift
    if groups["lock"] and not groups["manifest"]:
        names = ", ".join(f.path for f in groups["lock"][:3])
        risks.append(Finding("medium", "Lockfile changed without its manifest — version drift is unaudited", names))
    for f in groups["lock"]:
        if f.added + f.removed > 400:
            suggestions.append(f"`{f.path}` has a {f.added + f.removed}-line diff; summarise the dependency change in the PR body.")

    # 5. schema changes
    for f in groups["migration"]:
        risks.append(Finding(
            "medium",
            "Schema change: confirm it is backward compatible, or ship it as expand/contract",
            f.path,
        ))

    # 6. CI weakening
    for f in groups["ci"]:
        if f.removed > f.added:
            risks.append(Finding("medium", "CI workflow shrinks — a gate may be silently disabled", f.path))
        else:
            suggestions.append(f"CI config touched (`{f.path}`); confirm the pipeline still runs on this PR.")

    # 7. public API surface removal
    for f in pr.files:
        if os.path.basename(f.path) in ("__init__.py", "index.ts", "index.js", "mod.rs", "lib.rs"):
            for lineno, text in f.removed_lines:
                if re.search(r"^\s*(export|from|import|pub use|__all__)", text):
                    risks.append(Finding("medium", "Public export removed — potential breaking change", f"{f.path}:{lineno}"))

    # 8. binary blobs
    for f in groups["binary"]:
        risks.append(Finding("low", "Binary file changed — its contents are unreviewable in the diff", f.path))

    # 9. size
    total = pr.total_lines
    if total > 1000:
        risks.append(Finding("medium", f"Very large diff ({total} changed lines) — review depth is limited"))
        suggestions.append("Split this PR into smaller, independently reviewable changes.")
    elif total > 400:
        suggestions.append(f"Large diff ({total} lines) — a short walkthrough in the PR body would speed review up.")

    # 10. sensitive areas
    sensitive = [f.path for f in pr.files if SENSITIVE_PATH_RE.search(f.path)]
    if sensitive:
        suggestions.append(
            "Touches security-sensitive code ("
            + ", ".join(f"`{p}`" for p in sensitive[:3])
            + ") — request a second reviewer from the owning team."
        )

    if groups["docs"] and groups["source"]:
        suggestions.append("Source changed alongside docs; make sure the documented behaviour is the shipped behaviour.")

    if not suggestions:
        if any(r.severity == "high" for r in risks):
            suggestions.append(
                "Clear every 🔴 high-severity risk above before merge — each one has a direct "
                "diff-level fix (parameterise the query, drop `shell=True`, remove the secret, "
                "re-enable TLS verification)."
            )
        else:
            suggestions.append("No structural suggestions: the change is small and self-contained.")
    if not risks:
        risks.append(Finding("low", "No blocking risk found by static analysis", ""))

    confidence = "High"
    if total > 300 or sensitive:
        confidence = "Medium"
    if total > 1000 or len([r for r in risks if r.severity == "high"]) >= 2:
        confidence = "Low"

    summary = _summarise(pr, groups)
    return Review(summary=summary, risks=risks, suggestions=suggestions, confidence=confidence, engine="local")


def _summarise(pr: PullRequest, groups: Dict[str, List[FileDiff]]) -> str:
    parts: List[str] = []
    n = len(pr.files)
    parts.append(
        f"This PR touches {n} file{'s' if n != 1 else ''} "
        f"(+{sum(f.added for f in pr.files)}/−{sum(f.removed for f in pr.files)})."
    )
    areas = []
    for key, label in (("source", "source"), ("test", "tests"), ("docs", "docs"), ("ci", "CI"),
                       ("migration", "schema"), ("lock", "dependencies"), ("config", "configuration")):
        if groups[key]:
            areas.append(f"{len(groups[key])} {label}")
    if areas:
        parts.append("It changes " + ", ".join(areas) + ".")
    else:
        parts.append("No source files are touched.")
    if groups["test"]:
        parts.append("Tests are included, which is the right default for behaviour changes.")
    elif groups["source"]:
        parts.append("No tests are included, so the behaviour change rests on review alone.")
    return " ".join(parts[:3])


# --------------------------------------------------------------------------- #
# claude engine
# --------------------------------------------------------------------------- #
PROMPT = """You are reviewing a pull request. Reply with Markdown only, exactly these four sections and nothing else:

**Summary of changes**
2-3 sentences describing what the diff does and which areas it touches.

**Identified risks**
A bullet list. Each bullet: the risk, the file/line if you can identify one, and the concrete
failure it would cause. Say "None found" if you genuinely see no risk. Do not invent risks.

**Improvement suggestions**
A bullet list of concrete, actionable suggestions tied to this diff.

**Confidence score:** Low | Medium | High

Be specific. Do not restate the diff. Do not add any other section, preamble, or closing remark."""


def review_with_claude(pr: PullRequest, model: str, api_key: str) -> Optional[Review]:
    diff = pr.diff[:MAX_DIFF_CHARS]
    payload = {
        "model": model,
        "max_tokens": 2000,
        "system": PROMPT,
        "messages": [{
            "role": "user",
            "content": (
                f"PR: {pr.title}\nRepository: {pr.owner}/{pr.repo}\n"
                f"Description:\n{pr.body[:2000]}\n\nDiff:\n```diff\n{diff}\n```"
            ),
        }],
    }
    request = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        text = "".join(block.get("text", "") for block in data.get("content", []))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        print(f"warning: Claude API call failed ({exc}); falling back to local analysis", file=sys.stderr)
        return None

    confidence = "Medium"
    match = re.search(r"confidence score:?\**\s*\**\s*(low|medium|high)", text, re.I)
    if match:
        confidence = match.group(1).capitalize()

    def section(name: str) -> List[str]:
        block = re.search(
            r"\*\*" + re.escape(name) + r"\*\*\s*\n(.*?)(?=\n\*\*|\n##|\Z)", text, re.S | re.I
        )
        if not block:
            return []
        return [l.strip("-• ").strip() for l in block.group(1).strip().splitlines() if l.strip()]

    summary_lines = section("Summary of changes")
    risks_raw = section("Identified risks")
    suggestions = section("Improvement suggestions")

    if not (summary_lines or risks_raw or suggestions):
        print("warning: could not parse Claude output; falling back to local analysis", file=sys.stderr)
        return None

    risks = []
    for line in risks_raw:
        severity = "high" if re.search(r"\b(security|injection|secret|credential|rce|xss|data loss)\b", line, re.I) else "medium"
        if re.fullmatch(r"none( found)?\.?", line.strip(), re.I):
            continue
        risks.append(Finding(severity, line))
    return Review(
        summary=" ".join(summary_lines) or _summarise(pr, _classify(pr.files)),
        risks=risks or [Finding("low", "No blocking risk reported by the model", "")],
        suggestions=suggestions or ["No suggestions reported by the model."],
        confidence=confidence,
        engine="claude",
    )


# --------------------------------------------------------------------------- #
# github plumbing
# --------------------------------------------------------------------------- #
def parse_ref(ref: str) -> Tuple[str, str, int]:
    ref = ref.strip()
    match = re.search(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", ref)
    if match:
        return match.group(1), match.group(2), int(match.group(3))
    match = re.match(r"^([^/#\s]+)/([^/#\s]+)(?:#|/pull/)(\d+)$", ref)
    if match:
        return match.group(1), match.group(2), int(match.group(3))
    raise SystemExit(f"cannot parse PR reference: {ref!r} (expected owner/repo#123 or a PR URL)")


def gh_request(url: str, accept: str, token: Optional[str], method: str = "GET",
               body: Optional[dict] = None, timeout: int = 60) -> bytes:
    headers = {"accept": accept, "user-agent": f"claude-review/{VERSION}"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_pr(ref: str, token: Optional[str]) -> PullRequest:
    owner, repo, number = parse_ref(ref)
    base_url = f"{API_ROOT}/repos/{owner}/{repo}/pulls/{number}"
    meta = json.loads(gh_request(base_url, "application/vnd.github+json", token).decode("utf-8"))
    diff = gh_request(base_url, "application/vnd.github.v3.diff", token).decode("utf-8", "replace")
    pr = PullRequest(
        owner=owner,
        repo=repo,
        number=number,
        title=meta.get("title", ""),
        author=(meta.get("user") or {}).get("login", ""),
        body=meta.get("body") or "",
        base=(meta.get("base") or {}).get("ref", ""),
        head=(meta.get("head") or {}).get("ref", ""),
        additions=meta.get("additions", 0),
        deletions=meta.get("deletions", 0),
        changed_files=meta.get("changed_files", 0),
        diff=diff,
        files=parse_diff(diff),
    )
    return pr


def post_comment(pr: PullRequest, body: str, token: str) -> str:
    url = f"{API_ROOT}/repos/{pr.owner}/{pr.repo}/issues/{pr.number}/comments"
    data = json.loads(gh_request(url, "application/vnd.github+json", token,
                                 method="POST", body={"body": body}).decode("utf-8"))
    return data.get("html_url", "")


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_markdown(review: Review, pr: PullRequest) -> str:
    lines = [
        "## 🤖 Automated review",
        "",
        f"> {pr.title or '(untitled)'} — {pr.changed_files or len(pr.files)} files, "
        f"+{sum(f.added for f in pr.files)}/−{sum(f.removed for f in pr.files)}, "
        f"engine: `{review.engine}`",
        "",
        "**Summary of changes**",
        "",
        review.summary,
        "",
        "**Identified risks**",
        "",
    ]
    lines += [risk.render() for risk in review.risks]
    lines += ["", "**Improvement suggestions**", ""]
    lines += [f"- {s}" for s in review.suggestions]
    lines += [
        "",
        f"**Confidence score:** {review.confidence}",
        "",
        "<details><summary>How this review was produced</summary>",
        "",
        f"- PR: {pr.url}",
        f"- engine: `{review.engine}`"
        + (" (Anthropic API)" if review.engine == "claude" else " (deterministic static analysis of the diff)"),
        f"- files parsed: {len(pr.files)}",
        f"- diff lines: {pr.total_lines}",
        "",
        "It reviews the diff, not the running program; treat it as a first pass, not a replacement "
        "for a human reviewer.",
        "",
        "</details>",
    ]
    return "\n".join(lines)


def render_json(review: Review, pr: PullRequest) -> str:
    return json.dumps({
        "pr": pr.url,
        "title": pr.title,
        "engine": review.engine,
        "summary": review.summary,
        "risks": [{"severity": r.severity, "message": r.message, "location": r.location} for r in review.risks],
        "suggestions": review.suggestions,
        "confidence": review.confidence,
        "stats": {
            "files": len(pr.files),
            "added": sum(f.added for f in pr.files),
            "removed": sum(f.removed for f in pr.files),
        },
    }, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="claude-review", description="Structured PR review.")
    ap.add_argument("--pr", help="PR URL or owner/repo#123")
    ap.add_argument("--diff-file", help="review a local diff instead of a PR")
    ap.add_argument("--title", default="", help="title to use with --diff-file")
    ap.add_argument("--body", default="", help="description to use with --diff-file")
    ap.add_argument("--engine", choices=["local", "claude"], default="local")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--out", "-o", help="write the review to this file")
    ap.add_argument("--comment", action="store_true", help="post the review as a PR comment")
    ap.add_argument("--version", action="version", version=f"claude-review {VERSION}")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    if args.diff_file:
        with open(args.diff_file, "r", encoding="utf-8", errors="replace") as fh:
            diff = fh.read()
        pr = PullRequest(owner="local", repo="local", number=0, title=args.title,
                         body=args.body, diff=diff, files=parse_diff(diff))
        pr.changed_files = len(pr.files)
    elif args.pr:
        try:
            pr = fetch_pr(args.pr, token)
        except urllib.error.HTTPError as exc:
            print(f"error: GitHub API {exc.code} for {args.pr} "
                  f"(set GITHUB_TOKEN if you are rate limited)", file=sys.stderr)
            return 2
        except urllib.error.URLError as exc:
            print(f"error: cannot reach GitHub: {exc}", file=sys.stderr)
            return 2
    else:
        ap.error("one of --pr or --diff-file is required")

    review: Optional[Review] = None
    if args.engine == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("warning: ANTHROPIC_API_KEY is not set; using local analysis", file=sys.stderr)
        else:
            review = review_with_claude(pr, args.model, api_key)
    if review is None:
        review = review_locally(pr)

    output = render_json(review, pr) if args.format == "json" else render_markdown(review, pr)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(output + "\n")
        print(f"wrote {args.out} ({review.engine} engine, confidence {review.confidence})", file=sys.stderr)
    else:
        print(output)

    if args.comment:
        if not token:
            print("error: --comment needs GITHUB_TOKEN", file=sys.stderr)
            return 2
        if pr.number == 0:
            print("error: --comment needs a real PR, not --diff-file", file=sys.stderr)
            return 2
        url = post_comment(pr, output, token)
        print(f"comment posted: {url}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
