#!/usr/bin/env bash
# Unload the watchdog LaunchAgent. Does not delete analysis archives or logs.
set -euo pipefail

LABEL="com.video-analysis.watchdog"
DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: launchd uninstall is macOS-only." >&2
  exit 1
fi

uid="$(id -u)"
if launchctl print "gui/${uid}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${uid}/${LABEL}"
  echo "Booted out gui/${uid}/${LABEL}"
else
  echo "LaunchAgent ${LABEL} is not loaded."
fi

if [[ -f "$DEST" ]]; then
  rm -f "$DEST"
  echo "Removed $DEST"
else
  echo "No plist at $DEST"
fi

echo "Analysis archive, /tmp/video-analysis-watchdog.* logs, and heartbeat files were kept."
