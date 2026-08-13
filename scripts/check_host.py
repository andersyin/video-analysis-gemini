#!/usr/bin/env python3
"""First-run host checks: Python, ffmpeg/ffprobe, Whisper, MEDIA_DIR.

This does not call the Gemini API and does not process video.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from local_paths import LOCAL_ENV, has_placeholder, resolve_tool

MIN_PYTHON = (3, 9)


def _ok(msg):
    print("OK   {0}".format(msg))


def _warn(msg):
    print("WARN {0}".format(msg))


def _fail(msg):
    print("FAIL {0}".format(msg))


def main():
    errors = 0

    if sys.version_info < MIN_PYTHON:
        _fail("Python {0}.{1}+ required (found {2})".format(
            MIN_PYTHON[0], MIN_PYTHON[1], sys.version.split()[0]))
        errors += 1
    else:
        _ok("Python {0}".format(sys.version.split()[0]))

    for tool in ("ffmpeg", "ffprobe"):
        resolved = resolve_tool(tool)
        if resolved != tool or shutil.which(tool):
            _ok("{0} → {1}".format(tool, resolved if resolved != tool else shutil.which(tool)))
        else:
            _fail("{0} not found (macOS: brew install ffmpeg)".format(tool))
            errors += 1

    whisper = resolve_tool("whisper")
    if whisper != "whisper" or shutil.which("whisper"):
        _ok("whisper → {0}".format(whisper if whisper != "whisper" else shutil.which("whisper")))
    else:
        _warn("whisper not on PATH (pip install openai-whisper). L1 STT will be empty.")

    media = os.environ.get("MEDIA_DIR", "")
    if not media:
        if LOCAL_ENV.is_file():
            _warn("MEDIA_DIR unset after loading local.env — edit {0}".format(LOCAL_ENV))
        else:
            _warn("MEDIA_DIR unset. Copy local.env.example to local.env or export MEDIA_DIR.")
    elif has_placeholder(media):
        _fail("MEDIA_DIR still contains a placeholder: {0!r}".format(media))
        errors += 1
    else:
        media_path = Path(media).expanduser()
        if media_path.is_dir():
            _ok("MEDIA_DIR={0}".format(media_path))
        else:
            _fail("MEDIA_DIR is not a directory: {0}".format(media_path))
            errors += 1

    print()
    if errors:
        print("{0} required check(s) failed.".format(errors))
        return 1
    print("Host checks passed. Layer 2/3 still need Gemini via Antigravity (no API key in this repo).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
