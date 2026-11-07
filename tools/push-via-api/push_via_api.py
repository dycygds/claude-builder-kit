#!/usr/bin/env python3
"""
push_via_api.py — publish the current git tree through GitHub's Git Data API.

Why this exists: on networks where `git push` cannot open a TCP connection to
github.com:443 (blackholed routes, aggressive filtering) while api.github.com stays
reachable, the Git protocol is simply unavailable. The REST API is not.

    $env:GITHUB_TOKEN = "ghp_..."
    python push_via_api.py --repo dycygds/claude-builder-kit --branch main

It creates one commit containing exactly the files `git ls-files` reports, preserving
the executable bit on scripts, then points the branch at it. Idempotent enough: if the
branch already exists, the new commit is added on top of the current head.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

API = "https://api.github.com"
EXECUTABLE = (".sh",)
EXECUTABLE_NAMES = ("claude-review",)
RETRIES = 6


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not value:
        raise SystemExit("GITHUB_TOKEN is not set")
    return value


def api(path: str, method: str = "GET", body: Optional[dict] = None) -> Tuple[int, dict]:
    """One API call, retried on transport failures (this network drops connections)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last: Optional[Exception] = None
    for attempt in range(1, RETRIES + 1):
        request = urllib.request.Request(
            API + path,
            data=data,
            method=method,
            headers={
                "authorization": f"token {token()}",
                "accept": "application/vnd.github+json",
                "content-type": "application/json",
                "user-agent": "push-via-api/1.0",
                "x-github-api-version": "2022-11-28",
                "connection": "close",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read().decode("utf-8")
                return response.status, (json.loads(payload) if payload.strip() else {})
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                parsed = {"message": payload[:300]}
            return exc.code, parsed
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            if attempt == RETRIES:
                break
            wait = min(2 ** attempt, 20)
            print(f"  retry {attempt}/{RETRIES - 1} in {wait}s ({type(exc).__name__})", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"network gave up on {method} {path}: {last}")


def git_blob_sha(raw: bytes) -> str:
    """The SHA GitHub will assign to this blob — computable locally, so a resumed
    upload never re-sends what already landed."""
    header = b"blob %d\0" % len(raw)
    return hashlib.sha1(header + raw).hexdigest()


def blob_exists(owner: str, name: str, sha: str) -> bool:
    status, _ = api(f"/repos/{owner}/{name}/git/blobs/{sha}")
    return status == 200



def tracked_files(root: str) -> List[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=root, capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")
    return [line for line in out.splitlines() if line.strip()]


def mode_for(path: str) -> str:
    base = os.path.basename(path)
    if base in EXECUTABLE_NAMES or base.endswith(EXECUTABLE):
        return "100755"
    return "100644"


def seed_empty_repo(owner: str, name: str, branch: str) -> bool:
    """A freshly created repo has no commits, and the Git Data API answers 409
    "Git Repository is empty" until one exists. Seed one through the Contents API."""
    status, _ = api(f"/repos/{owner}/{name}/git/ref/heads/{branch}")
    if status == 200:
        return True
    status, payload = api(f"/repos/{owner}/{name}/contents/README.md", "PUT", {
        "message": "chore: initialise repository",
        "branch": branch,
        "content": base64.b64encode(
            b"# " + name.encode() + b"\n\nInitialised by push_via_api.py\n"
        ).decode("ascii"),
    })
    if status in (200, 201):
        print("seeded   : initial commit via Contents API")
        return True
    print(f"seed FAILED: {status} {payload.get('message')}", file=sys.stderr)
    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Push the working tree through the GitHub API.")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="", help="commit message (default: HEAD commit message)")
    ap.add_argument("--root", default=".", help="repository root")
    args = ap.parse_args(argv)

    owner, _, name = args.repo.partition("/")
    if not name:
        raise SystemExit("--repo must be owner/name")

    root = os.path.abspath(args.root)
    files = tracked_files(root)
    if not files:
        raise SystemExit("no tracked files — is this a git repository?")

    message = args.message.strip()
    if not message:
        message = subprocess.run(
            ["git", "-c", "core.pager=cat", "log", "-1", "--pretty=%B"],
            cwd=root, capture_output=True, check=True,
        ).stdout.decode("utf-8", "replace").strip() or "Update via API"
    # API commits carry one message; keep the subject plus a short trailer.
    message = message.split("\n\n")[0]

    print(f"repo     : {owner}/{name}")
    print(f"branch   : {args.branch}")
    print(f"files    : {len(files)}")
    print(f"message  : {message.splitlines()[0][:80]}")

    if not seed_empty_repo(owner, name, args.branch):
        return 2

    # 1. blobs (skip what already exists — a resumed run continues where the last died)
    tree: List[Dict[str, str]] = []
    for index, path in enumerate(files, start=1):
        with open(os.path.join(root, path), "rb") as fh:
            raw = fh.read()
        sha = git_blob_sha(raw)
        if blob_exists(owner, name, sha):
            tree.append({"path": path, "mode": mode_for(path), "type": "blob", "sha": sha})
            print(f"  [{index:2}/{len(files)}] cached   {path}")
            continue
        status, payload = api(f"/repos/{owner}/{name}/git/blobs", "POST", {
            "content": base64.b64encode(raw).decode("ascii"),
            "encoding": "base64",
        })
        if status not in (200, 201):
            print(f"  [{index:2}/{len(files)}] FAILED   {path}: {status} {payload.get('message')}", file=sys.stderr)
            return 2
        tree.append({"path": path, "mode": mode_for(path), "type": "blob", "sha": payload["sha"]})
        print(f"  [{index:2}/{len(files)}] uploaded {path}")

    # 2. tree
    status, payload = api(f"/repos/{owner}/{name}/git/trees", "POST", {"tree": tree})
    if status not in (200, 201):
        print(f"tree FAILED: {status} {payload.get('message')}", file=sys.stderr)
        return 2
    tree_sha = payload["sha"]
    print(f"tree     : {tree_sha}")

    # 3. parents (if the branch already exists)
    parents: List[str] = []
    status, payload = api(f"/repos/{owner}/{name}/git/ref/heads/{args.branch}")
    if status == 200:
        parents = [payload["object"]["sha"]]
        print(f"parent   : {parents[0]}")

    # 4. commit
    status, payload = api(f"/repos/{owner}/{name}/git/commits", "POST", {
        "message": message, "tree": tree_sha, "parents": parents,
    })
    if status not in (200, 201):
        print(f"commit FAILED: {status} {payload.get('message')}", file=sys.stderr)
        return 2
    commit_sha = payload["sha"]
    print(f"commit   : {commit_sha}")

    # 5. move the branch
    if parents:
        status, payload = api(f"/repos/{owner}/{name}/git/refs/heads/{args.branch}", "PATCH", {
            "sha": commit_sha, "force": True,
        })
    else:
        status, payload = api(f"/repos/{owner}/{name}/git/refs", "POST", {
            "ref": f"refs/heads/{args.branch}", "sha": commit_sha,
        })
    if status not in (200, 201):
        print(f"ref FAILED: {status} {payload.get('message')}", file=sys.stderr)
        return 2

    # 6. make sure the branch is the default one
    api(f"/repos/{owner}/{name}", "PATCH", {"default_branch": args.branch})

    print()
    print(f"pushed   : https://github.com/{owner}/{name}/tree/{args.branch}")
    print(f"commit   : https://github.com/{owner}/{name}/commit/{commit_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
