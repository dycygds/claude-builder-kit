#!/usr/bin/env bash
# Thin wrapper so the skill works exactly as the issue asks: `bash changelog.sh`.
#
#   bash changelog.sh                  # preview the next section on stdout
#   bash changelog.sh --write          # prepend it into CHANGELOG.md
#   bash changelog.sh --since v1.2.0 --repo owner/name
#
# Set PYTHON to override interpreter discovery.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pick_python() {
  local candidate
  for candidate in "${PYTHON:-}" python3 python; do
    [ -n "$candidate" ] || continue
    # `python3` on Windows is often a Microsoft Store stub that exits non-zero
    # and prints nothing, so probe the interpreter instead of trusting PATH.
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "error: Python 3.8+ not found (set PYTHON=/path/to/python3)" >&2
  exit 127
fi

exec "$PY" "$DIR/changelog.py" "$@"
