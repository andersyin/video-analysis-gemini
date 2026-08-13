#!/usr/bin/env bash
# Install the watchdog LaunchAgent. Writes a plist with real paths; does not sed the repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.video-analysis.watchdog"
DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: launchd install is macOS-only." >&2
  exit 1
fi

if [[ -f "$PROJECT_ROOT/local.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/local.env"
  set +a
fi

if [[ -z "${MEDIA_DIR:-}" ]]; then
  echo "error: MEDIA_DIR is not set. Copy local.env.example to local.env and edit it." >&2
  exit 1
fi
if [[ "$MEDIA_DIR" == *"{{"* || "$PROJECT_ROOT" == *"{{"* ]]; then
  echo "error: MEDIA_DIR or PROJECT_ROOT still contains a placeholder." >&2
  exit 1
fi
if [[ ! -d "$MEDIA_DIR" ]]; then
  echo "error: MEDIA_DIR is not a directory: $MEDIA_DIR" >&2
  exit 1
fi
if [[ ! -x "$SCRIPT_DIR/watchdog-wrapper.sh" ]]; then
  echo "error: watchdog-wrapper.sh is missing or not executable." >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"

cat > "$DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_ROOT}/launchd/watchdog-wrapper.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>MEDIA_DIR</key>
        <string>${MEDIA_DIR}</string>
        <key>PROJECT_ROOT</key>
        <string>${PROJECT_ROOT}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/video-analysis-watchdog.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/video-analysis-watchdog.err.log</string>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
EOF

uid="$(id -u)"
if launchctl print "gui/${uid}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${uid}/${LABEL}" || true
fi
launchctl bootstrap "gui/${uid}" "$DEST"
echo "Installed $DEST"
echo "Next: launchctl kickstart gui/${uid}/${LABEL}"
echo "Liveness: check mtime of /tmp/video-analysis-watchdog.json (or KB_BASE heartbeat file)."
