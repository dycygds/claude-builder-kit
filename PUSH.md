# Push this repo to GitHub — three paths, pick one

The kit is committed locally (`35 files, 4574 insertions`, branch will be `main`). Nothing
here can push itself: this machine has **no stored GitHub credential** —

```
~/.git-credentials                 missing
cmdkey /list | grep github         no entries
gh                                 not installed
git credential.helper              manager (opens an interactive GUI prompt)
```

So authentication is the only missing piece. Any one of these three finishes the job.

---

## Path A — one command, if you paste me a token (fastest, fully automated)

1. Open this pre-filled URL and click **Generate token** (scope: `repo`, expiry: 7 days):

   https://github.com/settings/tokens/new?scopes=repo,read:user&description=claude-builder-kit

2. Hand me the `ghp_…` string in chat, or run it yourself without showing it to anyone:

   ```powershell
   $env:GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxx"
   powershell -ExecutionPolicy Bypass -File .\push.ps1
   ```

`push.ps1` then: verifies who the token belongs to, creates `dycygds/claude-builder-kit`
(public, with description and topics) if it does not exist, pushes `main`, and prints the URL.
The token is used through an ephemeral HTTP header — it is **never** written to `.git/config`,
the remote URL, or shell history.

---

## Path B — you create the repo in the browser, I push

1. https://github.com/new → name `claude-builder-kit`, Public, **do not** add a README,
   .gitignore or license (the repo already has them).
2. Come back here and say "repo created". I will add the remote and push the moment a
   credential exists (Path A step 2 or Path C).

---

## Path C — you own the auth, no token in chat

```powershell
# install the GitHub CLI, then log in once (browser flow, no token paste)
winget install --id GitHub.cli -e
gh auth login          # GitHub.com → HTTPS → login with a web browser

# from now on, gh supplies credentials to git automatically
cd C:\Users\N\Documents\deepseek-harness\default-workspace\claude-builder-kit
gh repo create claude-builder-kit --public --source . --remote origin --push `
  --description "Claude Code builder kit: destructive-command hook, changelog skill, PR reviewer, and a bounty scanner that checks whether a bounty can actually pay."
```

That single `gh repo create … --push` does creation, remote, and push in one shot.

---

## After the push (two minutes, big payoff)

**Status on this machine:** the repo is already live at
`https://github.com/dycygds/claude-builder-kit` — `git push` cannot reach github.com:443 on
this network (TCP blocked, API fine), so it was published through
[`tools/push-via-api`](tools/push-via-api/push_via_api.py) instead.

### 1. Pin the repo so it is the first thing on your profile

1. Open <https://github.com/dycygds>
2. Click **Customize your pins** (right of the *Pinned* heading), or the pencil icon next to it
3. Tick **claude-builder-kit**; untick anything you do not want shown (max 6)
4. Click **Save pins**

GitHub has no API for pinned items — this one is UI-only.

### 2. Add a profile README (the strongest single move)

A repository named exactly `dycygds` renders its `README.md` at the top of your profile page.
The content is written and ready in [`outreach/profile-readme.md`](outreach/profile-readme.md):

```powershell
# creates dycygds/dycygds and publishes the profile README
$env:GITHUB_TOKEN = "ghp_..."
python tools/push-via-api/publish_profile.py
```

Edit `outreach/profile-readme.md` first if you want different wording — it is plain Markdown.

### 3. Topics (already set by `push.ps1`)

```powershell
gh repo edit dycygds/claude-builder-kit `
  --add-topic claude-code,claude,ai-agents,devtools,hooks,bounty
```


Then the launch material is already written and points at the live URL:

| File | Use |
|---|---|
| `outreach/x-thread.md` | 6-tweet thread, links already filled in |
| `outreach/reddit-post.md` | r/ClaudeAI / r/ClaudeCode post + 4 prepared replies |
| `outreach/live-bounty-leads.md` | the two funded bounties worth claiming first |
| `outreach/pr-description.md` | PR body + claim-comment templates |

## Checklist before the first post

- [ ] `python -m unittest discover -s tests` green in `hooks/` and `agents/pr-reviewer/`
      (40 + 27 tests; both verified on this machine)
- [ ] README renders: the acceptance-mapping tables are the part reviewers read
- [ ] `outreach/x-thread.md` tweet 2 has the `DEMO.txt` screenshot attached
- [ ] repo topics set, repo pinned on the profile
