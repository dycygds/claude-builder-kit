@echo off
REM claude-review for Windows cmd/PowerShell users.
REM   claude-review --pr https://github.com/owner/repo/pull/123
setlocal
set "DIR=%~dp0"
python "%DIR%claude_review.py" %*
