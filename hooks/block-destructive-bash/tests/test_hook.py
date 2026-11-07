#!/usr/bin/env python3
"""
Test suite for block_destructive.py — stdlib only, no pytest required.

    python -m unittest discover -s tests -v

Every test drives the hook exactly the way Claude Code does: JSON on stdin,
assert on the process exit code (2 = blocked, 0 = allowed) and on the log file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "block_destructive.py"


class HookRunner:
    """Runs the hook as a subprocess with an isolated log file."""

    def __init__(self, tmpdir: Path):
        self.log = tmpdir / "blocked.log"

    def run(self, command: str, cwd: str = "/project/app", extra_args=()):
        payload = {
            "session_id": "test-session",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": cwd,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command, "description": "test"},
        }
        env = dict(os.environ)
        env["BLOCK_DESTRUCTIVE_LOG"] = str(self.log)
        proc = subprocess.run(
            [sys.executable, str(HOOK), *extra_args],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        return proc

    def log_lines(self):
        if not self.log.exists():
            return []
        return [l for l in self.log.read_text(encoding="utf-8").splitlines() if l.strip()]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.hook = HookRunner(self.tmpdir)

    def tearDown(self):
        self._tmp.cleanup()

    # helpers -------------------------------------------------------------
    def assertBlocked(self, command: str, rule: str | None = None):
        proc = self.hook.run(command)
        self.assertEqual(
            proc.returncode, 2,
            f"expected BLOCK for {command!r}, got exit {proc.returncode}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}",
        )
        self.assertIn("BLOCKED by block-destructive-bash", proc.stderr)
        self.assertIn("Command:", proc.stderr)
        self.assertIn("What to do instead:", proc.stderr)
        if rule:
            self.assertIn(f"[{rule}]", proc.stderr)
        return proc

    def assertAllowed(self, command: str):
        proc = self.hook.run(command)
        self.assertEqual(
            proc.returncode, 0,
            f"expected ALLOW for {command!r}, got exit {proc.returncode}\n"
            f"stderr={proc.stderr}",
        )
        self.assertEqual(proc.stdout.strip(), "", "allow must not print to stdout")
        self.assertEqual(proc.stderr.strip(), "", "allow must be silent")
        return proc


# --------------------------------------------------------------------------- #
# 1. required patterns from the bounty checklist
# --------------------------------------------------------------------------- #
class RequiredPatterns(Base):
    def test_rm_rf_root(self):
        self.assertBlocked("rm -rf /", "rm_critical_path")

    def test_rm_rf_home(self):
        self.assertBlocked("rm -rf ~/", "rm_critical_path")

    def test_rm_rf_etc(self):
        self.assertBlocked("rm -rf /etc", "rm_critical_path")

    def test_rm_rf_arbitrary_project_dir(self):
        self.assertBlocked("rm -rf src", "rm_recursive_force")

    def test_rm_r_variants(self):
        for cmd in ("rm -fr logs", "rm -Rf logs", "rm -r -f logs",
                    "rm --recursive --force logs", "rm -rfv logs"):
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd, "rm_recursive_force")

    def test_rm_no_preserve_root(self):
        self.assertBlocked("rm -rf --no-preserve-root /", "rm_no_preserve_root")

    def test_drop_table(self):
        self.assertBlocked("psql -c 'DROP TABLE users'", "sql_drop")

    def test_drop_database(self):
        self.assertBlocked('mysql -e "DROP DATABASE prod"', "sql_drop")

    def test_truncate(self):
        self.assertBlocked("psql -c 'TRUNCATE TABLE orders'", "sql_truncate")

    def test_delete_without_where(self):
        self.assertBlocked("psql -c 'DELETE FROM users;'", "sql_delete_without_where")

    def test_delete_multi_statement_without_where(self):
        self.assertBlocked(
            "psql -c 'SELECT 1; DELETE FROM audit_log;'", "sql_delete_without_where"
        )

    def test_git_push_force(self):
        for cmd in ("git push --force", "git push -f origin main",
                    "git push --force origin feature", "git -C /repo push -uf origin main"):
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd, "git_push_force")


# --------------------------------------------------------------------------- #
# 2. no interference with normal commands  (bounty checklist item 5)
# --------------------------------------------------------------------------- #
class NoFalsePositives(Base):
    def test_normal_shell_commands(self):
        for cmd in (
            "ls -la",
            "npm run build",
            "npm test -- --watch=false",
            "git status",
            "git commit -m 'feat: add hook'",
            "git push origin main",
            "git push origin feature/x",
            "python -m unittest discover -s tests -v",
            "pip install -r requirements.txt",
            "cat README.md | head -20",
            "grep -rn 'TODO' src/",
            "docker build -t app:latest .",
            "rm file.txt",
            "rm -i notes.md",
            "mkdir -p build && touch build/x",
        ):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd)

    def test_safe_build_dirs_may_be_wiped(self):
        for cmd in ("rm -rf ./node_modules", "rm -rf dist", "rm -rf build/",
                    "rm -rf .next", "rm -rf __pycache__", "rm -rf target"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd)

    def test_force_with_lease_is_allowed(self):
        self.assertAllowed("git push --force-with-lease origin main")

    def test_sql_with_where_is_allowed(self):
        self.assertAllowed("psql -c 'DELETE FROM users WHERE id = 42'")
        self.assertAllowed("sqlite3 app.db 'DELETE FROM sessions WHERE expires_at < 1'")

    def test_mentions_of_dangerous_words_are_allowed(self):
        # documentation, commit messages and greps must not be blocked
        self.assertAllowed('git commit -m "docs: explain why DROP TABLE is dangerous"')
        self.assertAllowed("grep -rn 'DELETE FROM' migrations/")
        self.assertAllowed('echo "rm -rf is banned here" >> NOTES.md')
        self.assertAllowed('python -c "print(\'rm -rf / is bad\')"')


# --------------------------------------------------------------------------- #
# 3. bypass resistance  (this is what separates this hook from the 2400 PRs)
# --------------------------------------------------------------------------- #
class BypassResistance(Base):
    def test_quote_obfuscation(self):
        self.assertBlocked("r''m -rf /", "rm_critical_path")
        self.assertBlocked('r"m" -rf /etc', "rm_critical_path")
        self.assertBlocked("\\rm -rf /", "rm_critical_path")

    def test_ifs_obfuscation(self):
        self.assertBlocked("rm${IFS}-rf${IFS}/", "rm_critical_path")

    def test_nested_shell(self):
        self.assertBlocked('bash -c "rm -rf /"', "rm_critical_path")
        self.assertBlocked("sh -c 'git push --force origin main'", "git_push_force")

    def test_eval(self):
        self.assertBlocked("eval 'rm -rf /'", "rm_critical_path")

    def test_sudo_prefixed(self):
        self.assertBlocked("sudo rm -rf /etc", "rm_critical_path")

    def test_env_prefixed(self):
        self.assertBlocked("FOO=1 sudo -u root rm -rf /", "rm_critical_path")

    def test_sudo_git_push_force(self):
        self.assertBlocked("sudo -E git push --force origin main", "git_push_force")

    def test_chained_segments(self):
        self.assertBlocked("cd /tmp && rm -rf /", "rm_critical_path")
        self.assertBlocked("npm run build; rm -rf ~/", "rm_critical_path")
        self.assertBlocked("echo start && bash -c 'rm -rf /var'", "rm_critical_path")

    def test_base64_pipe(self):
        # echo 'rm -rf /' | base64   ->  cm0gLXJmIC8=
        self.assertBlocked("echo cm0gLXJmIC8= | base64 -d | bash", "rm_critical_path")

    def test_find_delete(self):
        self.assertBlocked("find / -delete", "find_delete")
        self.assertBlocked("find . -name '*.py' -exec rm {} \\;", "find_delete")

    def test_dd_to_device(self):
        self.assertBlocked("dd if=/dev/zero of=/dev/sda bs=1M", "disk_destroy")
        self.assertBlocked("cat image.iso > /dev/nvme0n1", "disk_destroy")

    def test_mkfs(self):
        self.assertBlocked("mkfs.ext4 /dev/sdb1", "disk_destroy")

    def test_xargs_rm(self):
        self.assertBlocked("find src -name '*.js' | xargs rm -rf", "rm_recursive_force")


# --------------------------------------------------------------------------- #
# 4. logging contract: timestamp + attempted command + project path
# --------------------------------------------------------------------------- #
class Logging(Base):
    def test_log_has_required_fields(self):
        proc = self.hook.run("rm -rf /", cwd="/project/payments")
        self.assertEqual(proc.returncode, 2)
        lines = self.hook.log_lines()
        self.assertEqual(len(lines), 1, f"expected exactly one log line, got {lines}")
        line = lines[0]
        self.assertRegex(line, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")   # timestamp
        self.assertIn("rule=rm_critical_path", line)
        self.assertIn("project=/project/payments", line)                    # project path
        self.assertIn(json.dumps("rm -rf /", ensure_ascii=False), line)     # command

    def test_log_created_on_first_block(self):
        self.assertFalse(self.hook.log.exists())
        self.hook.run("git push --force")
        self.assertTrue(self.hook.log.exists())

    def test_no_log_on_allow(self):
        self.hook.run("npm run build")
        self.assertEqual(self.hook.log_lines(), [])

    def test_log_appends_and_escapes_newlines(self):
        self.hook.run("rm -rf /")
        self.hook.run("git push --force")
        lines = self.hook.log_lines()
        self.assertEqual(len(lines), 2)
        self.assertIn("rule=rm_critical_path", lines[0])
        self.assertIn("rule=git_push_force", lines[1])

    def test_message_tells_claude_the_log_path(self):
        proc = self.hook.run("rm -rf /")
        self.assertIn(str(self.hook.log), proc.stderr)


# --------------------------------------------------------------------------- #
# 5. hook protocol robustness: never break the session
# --------------------------------------------------------------------------- #
class Protocol(Base):
    def test_garbage_stdin_exits_zero(self):
        env = dict(os.environ)
        env["BLOCK_DESTRUCTIVE_LOG"] = str(self.hook.log)
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json at all",
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0)

    def test_empty_stdin_exits_zero(self):
        env = dict(os.environ)
        env["BLOCK_DESTRUCTIVE_LOG"] = str(self.hook.log)
        proc = subprocess.run([sys.executable, str(HOOK)], input="",
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0)

    def test_payload_without_command_exits_zero(self):
        env = dict(os.environ)
        env["BLOCK_DESTRUCTIVE_LOG"] = str(self.hook.log)
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}}
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0)

    def test_json_decision_mode(self):
        proc = self.hook.run("rm -rf /", extra_args=("--json",))
        self.assertEqual(proc.returncode, 2)
        decision = json.loads(proc.stdout)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("BLOCKED", decision["hookSpecificOutput"]["permissionDecisionReason"])

    def test_selftest_flag_passes(self):
        proc = subprocess.run([sys.executable, str(HOOK), "--selftest"],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("FAIL", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
