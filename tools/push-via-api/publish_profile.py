#!/usr/bin/env python3
"""
publish_profile.py — publish outreach/profile-readme.md as a GitHub profile README.

A repository named exactly like your account (`dycygds/dycygds`) renders its README at the
top of your profile page. This creates that repository if needed and writes the file.

    $env:GITHUB_TOKEN = "ghp_..."
    python publish_profile.py

Optional: --repo dycygds/dycygds --source ../outreach/profile-readme.md
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Sequence, Tuple

API = "https://api.github.com"


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not value:
        raise SystemExit("GITHUB_TOKEN is not set")
    return value


def api(path: str, method: str = "GET", body: Optional[dict] = None) -> Tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(1, 5):
        request = urllib.request.Request(
            API + path, data=data, method=method,
            headers={
                "authorization": f"token {token()}",
                "accept": "application/vnd.github+json",
                "content-type": "application/json",
                "user-agent": "publish-profile/1.0",
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
                return exc.code, json.loads(payload)
            except json.JSONDecodeError:
                return exc.code, {"message": payload[:300]}
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 4:
                raise SystemExit(f"network gave up: {exc}")
            time.sleep(2 * attempt)
    raise SystemExit("unreachable")


def main(argv: Optional[Sequence[str]] = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Publish a GitHub profile README.")
    ap.add_argument("--repo", default="", help="owner/owner (default: <me>/<me>)")
    ap.add_argument("--source", default=str(here.parent.parent / "outreach" / "profile-readme.md"))
    args = ap.parse_args(argv)

    status, me = api("/user")
    if status != 200:
        print(f"token rejected: {status} {me.get('message')}", file=sys.stderr)
        return 2
    login = me["login"]

    repo = args.repo or f"{login}/{login}"
    owner, _, name = repo.partition("/")
    if not name:
        raise SystemExit("--repo must be owner/name")

    status, existing = api(f"/repos/{owner}/{name}")
    if status == 404:
        status, created = api("/user/repos", "POST", {
            "name": name,
            "description": "Profile README",
            "private": False,
            "auto_init": False,
            "has_issues": False,
            "has_wiki": False,
            "has_projects": False,
        })
        if status not in (200, 201):
            print(f"cannot create {repo}: {status} {created.get('message')}", file=sys.stderr)
            return 2
        print(f"created  : https://github.com/{repo}")
    else:
        print(f"exists   : https://github.com/{repo}")

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    content = source.read_bytes()

    # the Contents API needs the current blob sha to update an existing file
    status, current = api(f"/repos/{owner}/{name}/contents/README.md")
    payload = {
        "message": "docs: profile README — claude-builder-kit",
        "content": base64.b64encode(content).decode("ascii"),
    }
    if status == 200:
        payload["sha"] = current["sha"]
        print(f"updating : README.md (sha {current['sha'][:7]})")
    else:
        print("creating : README.md")

    status, result = api(f"/repos/{owner}/{name}/contents/README.md", "PUT", payload)
    if status not in (200, 201):
        print(f"publish FAILED: {status} {result.get('message')}", file=sys.stderr)
        return 2

    print()
    print(f"published: https://github.com/{repo}#readme")
    print(f"profile  : https://github.com/{login}")
    print()
    print("next     : pin claude-builder-kit (Profile -> Customize your pins -> tick it -> Save)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
