#!/usr/bin/env python3
"""Resolve local paths from the environment without mutating the repo.

First-run contract:
  - Copy local.env.example → local.env (gitignored) or export MEDIA_DIR.
  - Scripts refuse to run if a {{PLACEHOLDER}} is still present.
  - Do not sed-replace committed source files.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV = REPO_ROOT / "local.env"

_HOMEBREW_BIN_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path.home() / ".local" / "bin",
)


def load_local_env(path=None):
    """Load KEY=value pairs from local.env into os.environ (do not override)."""
    env_path = Path(path) if path else LOCAL_ENV
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


def has_placeholder(value):
    return bool(value) and bool(PLACEHOLDER_RE.search(str(value)))


def refuse_placeholder(value, name):
    """Return value or raise SystemExit if it still contains {{PLACEHOLDER}}."""
    if has_placeholder(value):
        sys.exit(
            "error: {name} still contains a placeholder ({value!r}). "
            "Set {name} in the environment or local.env. "
            "Do not sed-replace files in the repo.".format(name=name, value=value)
        )
    return value


def resolve_archive_dir(cli_value=None):
    """Archive root: --archive-dir, else $MEDIA_DIR/analysis_archive."""
    if cli_value:
        refuse_placeholder(cli_value, "--archive-dir")
        return Path(cli_value).expanduser()
    media = os.environ.get("MEDIA_DIR", "")
    if not media:
        sys.exit(
            "error: MEDIA_DIR is not set and --archive-dir was not given. "
            "Copy local.env.example to local.env and set MEDIA_DIR, "
            "or pass --archive-dir /path/to/analysis_archive."
        )
    refuse_placeholder(media, "MEDIA_DIR")
    return Path(media).expanduser() / "analysis_archive"


def default_status_dir():
    """Watchdog heartbeat dir: $KB_BASE/... if set, otherwise /tmp."""
    kb = os.environ.get("KB_BASE", "")
    if kb and not has_placeholder(kb):
        return Path(kb).expanduser() / "raw" / "系统" / "watchdog心跳"
    return Path("/tmp")


def resolve_tool(name):
    """Find a binary on PATH, then Homebrew / ~/.local/bin. Falls back to name."""
    from shutil import which

    found = which(name)
    if found:
        return found
    for directory in _HOMEBREW_BIN_DIRS:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return name


def load_analyses(archive_dir):
    """Load (account, video_id, data) triples from an analysis archive."""
    root = Path(archive_dir)
    if not root.is_dir():
        sys.exit("error: archive directory does not exist: {0}".format(root))
    all_data = []
    for acct_dir in sorted(root.iterdir()):
        if not acct_dir.is_dir() or acct_dir.name.startswith(".") or acct_dir.name.startswith("_"):
            continue
        videos = acct_dir / "videos"
        if not videos.is_dir():
            continue
        for path in sorted(videos.glob("*/analysis_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            all_data.append((acct_dir.name, path.parent.name, data))
    return all_data
