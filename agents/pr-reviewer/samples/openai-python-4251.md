## 🤖 Automated review

> feat(api): add stream options for agent sessions — 44 files, +394/−55, engine: `local`

**Summary of changes**

This PR touches 44 files (+394/−55). It changes 38 source, 2 tests, 1 docs, 3 configuration. Tests are included, which is the right default for behaviour changes.

**Identified risks**

- 🟡 No blocking risk found by static analysis

**Improvement suggestions**

- Large diff (449 lines) — a short walkthrough in the PR body would speed review up.
- Touches security-sensitive code (`src/openai/resources/beta/agents/sessions/events.py`, `src/openai/resources/beta/agents/sessions/sessions.py`, `src/openai/types/beta/agent_session_created_event.py`) — request a second reviewer from the owning team.
- Source changed alongside docs; make sure the documented behaviour is the shipped behaviour.

**Confidence score:** Medium

<details><summary>How this review was produced</summary>

- PR: https://github.com/openai/openai-python/pull/4251
- engine: `local` (deterministic static analysis of the diff)
- files parsed: 44
- diff lines: 449

It reviews the diff, not the running program; treat it as a first pass, not a replacement for a human reviewer.

</details>
