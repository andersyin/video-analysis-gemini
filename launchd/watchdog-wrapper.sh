#!/usr/bin/env bash
# launchd entry (P0-4). Wrap python3 in bash so TCC/FDA matches other volume jobs.
# PROJECT_ROOT is this file's parent. MEDIA_DIR comes from the environment or local.env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/local.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/local.env"
  set +a
fi

if [[ -z "${MEDIA_DIR:-}" ]]; then
  echo "error: MEDIA_DIR is not set. Run launchd/install.sh after copying local.env.example." >&2
  exit 2
fi
if [[ "$MEDIA_DIR" == *"{{"* ]]; then
  echo "error: MEDIA_DIR still contains a placeholder: $MEDIA_DIR" >&2
  exit 2
fi

PYTHON3="$(command -v python3 || true)"
if [[ -z "$PYTHON3" ]]; then
  for candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /Library/Developer/CommandLineTools/usr/bin/python3 \
    /usr/bin/python3; do
    if [[ -x "$candidate" ]]; then
      PYTHON3="$candidate"
      break
    fi
  done
fi
if [[ -z "${PYTHON3:-}" ]]; then
  echo "error: python3 not found on PATH or in Homebrew / CLT locations." >&2
  exit 2
fi

exec "$PYTHON3" \
  "$PROJECT_ROOT/scripts/standalone_watchdog.py" \
  --archive-dir "${MEDIA_DIR%/}/analysis_archive" \
  --auto-finalize
