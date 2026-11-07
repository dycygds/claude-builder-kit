#!/usr/bin/env python3
"""
bounty-scout — find bounties that can actually pay out.

Most "bounty" issues on GitHub are decoration: a `$200` in the title, no funding behind
it, thousands of open PRs, and a maintainer who has never merged anything. This script
ranks issues by evidence instead of by the number in the title.

Signals it collects per candidate
  payout bot       a comment from the platform's own bot, which carries the receipt:
                   `algora-pbc[bot]` on Algora ("## 💎 $60 bounty"), `opire*[bot]` on Opire.
                   This is the only place the amount usually exists.
  funded label     `💎 Bounty` (Algora's label). A label alone is a claim, not a payment —
                   the label plus a payout bot plus a merging maintainer is the real signal.
  amount           from the bot comment first, then the title/body ($75, 75 USD)
  competition      comment count (proxy for `/attempt` swarms; GitHub has no cheap
                   linked-PR count)
  liveness         days since the issue was last updated
  maintainer       merged PRs in the repository over the last 180 days — the real gate:
                   a funded bounty still pays nothing if nobody merges

Usage
  python scout.py --label "💎 Bounty" --limit 30
  python scout.py --query 'label:"💎 Bounty" is:issue is:open' --min-amount 50 --json out.json
  python scout.py --verify owner/repo#123        # is this one issue funded?

Zero dependencies. Set GITHUB_TOKEN to lift the 60 requests/hour anonymous limit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

VERSION = "1.0.0"
API = "https://api.github.com"

FUNDED_LABELS = ("💎 bounty", "💎", "opire bounty")
BOUNTY_HINT_RE = re.compile(r"(?i)\b(bounty|reward|💎|💰)")
AMOUNT_PATTERNS = [
    re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)"),
    re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s?(?:USD|usd|EUR|eur|\$)"),
]


@dataclass
class Candidate:
    owner: str
    repo: str
    number: int
    title: str
    url: str
    labels: List[str] = field(default_factory=list)
    amount: Optional[float] = None
    comments: int = 0
    updated_days: float = 999.0
    merged_180d: int = 0
    score: float = 0.0
    funded_label: bool = False
    platform: str = ""
    evidence: str = ""
    notes: List[str] = field(default_factory=list)


def token() -> Optional[str]:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def gh(url: str, accept: str = "application/vnd.github+json") -> dict:
    headers = {"accept": accept, "user-agent": f"bounty-scout/{VERSION}"}
    tok = token()
    if tok:
        headers["authorization"] = f"Bearer {tok}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            body = exc.read().decode("utf-8", "replace")[:200]
            raise SystemExit(
                f"GitHub rate limit hit ({exc.code}). Set GITHUB_TOKEN to raise the limit.\n{body}"
            )
        raise


def parse_amount(*texts: str) -> Optional[float]:
    for text in texts:
        if not text:
            continue
        for pattern in AMOUNT_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    value = float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
                if 1 <= value <= 100_000:
                    return value
    return None


def days_since(iso: str) -> float:
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 999.0
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def merged_pr_count(owner: str, repo: str, cache: Dict[str, int]) -> int:
    key = f"{owner}/{repo}"
    if key in cache:
        return cache[key]
    since = datetime.now(timezone.utc).date().toordinal() - 180
    since_iso = datetime.fromordinal(since).isoformat()
    query = f"repo:{key} is:pr is:merged merged:>={since_iso}"
    url = f"{API}/search/issues?q={urllib.parse.quote(query)}&per_page=1"
    try:
        cache[key] = int(gh(url).get("total_count", 0))
    except urllib.error.HTTPError as exc:
        # Search has its own tight quota; a 403 here must not kill the whole scan.
        # Unknown maintainer activity is scored as "unproven", never as "active".
        if exc.code in (403, 429):
            cache[key] = -1
        else:
            cache[key] = 0
    except (urllib.error.URLError, SystemExit):
        cache[key] = -1
    return cache[key]


def search_candidates(query: str, limit: int) -> List[Candidate]:
    out: List[Candidate] = []
    cache: Dict[str, int] = {}
    page = 1
    while len(out) < limit and page <= 5:
        url = f"{API}/search/issues?q={urllib.parse.quote(query)}&per_page=50&page={page}&sort=updated"
        data = gh(url)
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            repo_url = item.get("repository_url", "")
            match = re.search(r"repos/([^/]+)/([^/]+)$", repo_url)
            if not match:
                continue
            owner, repo = match.group(1), match.group(2)
            labels = [l.get("name", "") for l in item.get("labels", [])]
            funded = any(l.strip().lower() in FUNDED_LABELS for l in labels)
            amount = parse_amount(item.get("title", ""), item.get("body") or "")
            cand = Candidate(
                owner=owner, repo=repo, number=item["number"], title=item.get("title", ""),
                url=item.get("html_url", ""), labels=labels, amount=amount,
                comments=item.get("comments", 0),
                updated_days=days_since(item.get("updated_at", "")),
                merged_180d=merged_pr_count(owner, repo, cache),
                funded_label=funded,
            )
            cand.score = score(cand)
            out.append(cand)
            if len(out) >= limit:
                break
        page += 1
    return out


def score(c: Candidate) -> float:
    """Expected value per unit of work. Transparent on purpose — no hidden weights."""
    pay = c.amount or 25.0
    competition = 1.0 + c.comments / 10.0
    if c.merged_180d < 0:
        maintainer = 0.6          # unknown (search quota hit) — unproven, not disqualifying
    elif c.merged_180d == 0:
        maintainer = 0.05         # never merges -> the bounty is decorative
    elif c.merged_180d < 5:
        maintainer = 0.4
    else:
        maintainer = 1.0
    if c.updated_days > 180:
        freshness = 0.3
    elif c.updated_days > 60:
        freshness = 0.7
    else:
        freshness = 1.0
    funded = 1.0 if c.funded_label else 0.5
    if c.platform in ("algora", "opire"):
        funded = 1.0
    return round(pay / competition * maintainer * freshness * funded, 2)


def platform_of(login: str, body: str, is_bot: bool) -> str:
    """Which bounty platform, if any, this *bot* comment proves.

    Humans say "opire" all day long (`/opire try` spam), so a human comment is
    never evidence of funding — only a bot account with the platform's own domain
    counts.
    """
    if not is_bot:
        return ""
    lower_login = login.lower()
    lower_body = body.lower()
    if "algora" in lower_login or "algora.io" in lower_body:
        return "algora"
    if "opire" in lower_login or "opire.dev" in lower_body:
        return "opire"
    if "bounty" in lower_body or "bounty" in lower_login:
        return "other-bot"
    return ""


def enrich(cand: Candidate) -> Candidate:
    """Read the bot comment that carries the real reward.

    A label is a claim; the payout bot comment is the receipt. On Algora-run
    bounties the amount exists *only* there — e.g. `## 💎 $60 bounty` — so a
    scout that parses just the title will report "?" for a real $60.
    """
    url = f"{API}/repos/{cand.owner}/{cand.repo}/issues/{cand.number}/comments?per_page=100"
    try:
        comments = gh(url)
    except (urllib.error.HTTPError, urllib.error.URLError, SystemExit):
        return cand
    for comment in comments:
        login = (comment.get("user") or {}).get("login", "")
        body = comment.get("body") or ""
        is_bot = (comment.get("user") or {}).get("type") == "Bot" or login.endswith("[bot]")
        platform = platform_of(login, body, is_bot)
        if platform:
            cand.platform = platform
            found = parse_amount(body)
            if found and not cand.amount:
                cand.amount = found
            cand.evidence = (body.splitlines()[0] if body else "")[:120]
            if found:
                break
    return cand


def verify(ref: str) -> int:
    """Check one issue for funding evidence."""
    match = re.match(r"^(?:https?://github\.com/)?([^/#\s]+)/([^/#\s]+?)(?:/issues/|#)(\d+)$", ref.strip())
    if not match:
        raise SystemExit(f"cannot parse {ref!r} (expected owner/repo#123)")
    owner, repo, number = match.group(1), match.group(2), int(match.group(3))
    issue = gh(f"{API}/repos/{owner}/{repo}/issues/{number}")
    labels = [l.get("name", "") for l in issue.get("labels", [])]
    funded = [l for l in labels if l.strip().lower() in FUNDED_LABELS]
    comments = gh(f"{API}/repos/{owner}/{repo}/issues/{number}/comments?per_page=100")
    platforms = []
    bot_amount = None
    for comment in comments:
        login = (comment.get("user") or {}).get("login", "")
        body = comment.get("body") or ""
        is_bot = (comment.get("user") or {}).get("type") == "Bot" or login.endswith("[bot]")
        platform = platform_of(login, body, is_bot)
        if platform and platform not in platforms:
            platforms.append(platform)
        if platform and bot_amount is None:
            bot_amount = parse_amount(body)
    merged = merged_pr_count(owner, repo, {})
    amount = parse_amount(issue.get("title", ""), issue.get("body") or "") or bot_amount

    print(f"{owner}/{repo}#{number}  {issue.get('title', '')}")
    print(f"  labels          : {', '.join(labels) or '(none)'}")
    print(f"  funded label    : {'YES -> ' + ', '.join(funded) if funded else 'no'}")
    print(f"  payout bot      : {', '.join(platforms) if platforms else 'none found'}")
    print(f"  amount          : {('$' + format(amount, '.0f')) if amount else 'not found'}"
          f"{' (from bot comment)' if bot_amount and bot_amount == amount else ''}")
    print(f"  comments        : {issue.get('comments', 0)}")
    print(f"  merged PRs 180d : {merged if merged >= 0 else '?'}")
    if merged < 0:
        print("  verdict         : search quota exhausted — rerun with GITHUB_TOKEN")
        return 1
    if (funded or platforms) and merged > 0:
        print("  verdict         : FUNDED and the maintainer merges — this one can actually pay")
        return 0
    if (funded or platforms) and merged == 0:
        print("  verdict         : FUNDED but the maintainer has not merged in 6 months — expect silence")
        return 1
    print("  verdict         : NO funding evidence — the dollar sign is text, not money")
    return 2


def render_markdown(cands: Sequence[Candidate]) -> str:
    lines = [
        "| score | amount | platform | issue | comments | merged PRs (180d) | last update |",
        "|---:|---:|---|---|---:|---:|---:|",
    ]
    for c in cands:
        merged = "?" if c.merged_180d < 0 else str(c.merged_180d)
        lines.append(
            f"| {c.score} | {'$' + format(c.amount, '.0f') if c.amount else '?'} "
            f"| {c.platform or '-'} "
            f"| [{c.owner}/{c.repo}#{c.number}]({c.url}) — {c.title[:60]} "
            f"| {c.comments} | {merged} | {c.updated_days:.0f}d ago |"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="bounty-scout", description="Rank GitHub bounties by payout evidence.")
    ap.add_argument("--query", help='GitHub search query (default: label:"💎 Bounty" is:issue is:open)')
    ap.add_argument("--label", default="💎 Bounty", help="funded label to search for")
    ap.add_argument("--limit", type=int, default=25, help="how many candidates to inspect")
    ap.add_argument("--min-amount", type=float, default=0.0, help="drop candidates below this amount")
    ap.add_argument("--enrich", type=int, default=12,
                    help="read the payout bot comments for the top N candidates (1 API call each)")
    ap.add_argument("--verify", help="check one issue for funding evidence (owner/repo#123)")
    ap.add_argument("--json", help="write results as JSON to this path")
    ap.add_argument("--markdown", help="write results as a Markdown table to this path")
    ap.add_argument("--version", action="version", version=f"bounty-scout {VERSION}")
    args = ap.parse_args(argv)

    if args.verify:
        return verify(args.verify)

    query = args.query or f'label:"{args.label}" is:issue is:open'
    candidates = search_candidates(query, args.limit)

    # Enrich the shortlist only: one API call per candidate, so cap it.
    head = candidates[:max(0, args.enrich)]
    for cand in head:
        enrich(cand)
        cand.score = score(cand)

    if args.min_amount:
        candidates = [c for c in candidates if (c.amount or 0) >= args.min_amount]
    candidates.sort(key=lambda c: c.score, reverse=True)

    if not candidates:
        print("no candidates found — try another label or query", file=sys.stderr)
        return 1

    print(render_markdown(candidates[:args.limit]))
    total = sum(c.amount or 0 for c in candidates)
    print(
        f"\n{len(candidates)} candidates, ${total:.0f} of stated bounties, "
        f"best score {candidates[0].score} ({candidates[0].owner}/{candidates[0].repo}"
        f"#{candidates[0].number})"
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump([c.__dict__ for c in candidates], fh, indent=2, ensure_ascii=False)
        print(f"wrote {args.json}", file=sys.stderr)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_markdown(candidates) + "\n")
        print(f"wrote {args.markdown}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
