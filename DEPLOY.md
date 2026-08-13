# Deployment Guide

## Environment Setup

Do **not** sed-replace committed scripts. Set paths in the environment or in a gitignored `local.env`.

```bash
cp local.env.example local.env
# edit MEDIA_DIR
python3 scripts/check_host.py
```

| Variable | Meaning | Example |
|----------|---------|---------|
| `MEDIA_DIR` | Media / archive parent directory | `/home/user/Media` |
| `KB_BASE` | Optional watchdog heartbeat parent (unset → `/tmp`) | `/home/user/kb` |

`PROJECT_ROOT` is derived from each script's location. Scripts refuse to run if a `{{PLACEHOLDER}}` is still present.

This repo does not read `GEMINI_API_KEY`. Layer 2/3 run inside Antigravity / Gemini (`view_file`). Do not commit API keys or personal paths.

## Dependencies

```bash
# Python standard library only — no pip packages needed for core scripts
# External tools:
brew install ffmpeg          # ffprobe + ffmpeg
pip install openai-whisper   # STT transcription
python3 scripts/check_host.py
```

Intel and Apple Silicon Homebrew prefixes (`/usr/local/bin`, `/opt/homebrew/bin`) plus `~/.local/bin` are searched automatically.

## Quick Start

See [SKILL.md](SKILL.md) for the full usage guide.

```bash
export MEDIA_DIR="$HOME/Media"
python3 scripts/batch_preprocess.py \
  --videos-dir "$MEDIA_DIR/AccountA" \
  --account AccountA \
  --archive-dir "$MEDIA_DIR/analysis_archive"
```

Audit scripts accept `--archive-dir` (or `$MEDIA_DIR/analysis_archive`):

```bash
python3 scripts/cross_validate.py --archive-dir "$MEDIA_DIR/analysis_archive"
```

## Launchd Configuration

```bash
# Requires MEDIA_DIR in local.env or the environment. macOS only.
bash launchd/install.sh
launchctl kickstart "gui/$(id -u)/com.video-analysis.watchdog"

# Uninstall (keeps archives and /tmp logs)
bash launchd/uninstall.sh
```

Do not copy the committed plist by hand — `install.sh` writes one with real paths into `~/Library/LaunchAgents/`.

Liveness is the heartbeat file mtime, not `launchctl list`. Default heartbeat: `/tmp/video-analysis-watchdog.json`.

## Project Structure

```
video-analysis-gemini/
├── SKILL.md                    # Core skill specification
├── local.env.example           # Path config template
├── assets/                     # Output templates
├── experiments/                # A/B test scripts
├── launchd/                    # macOS watchdog install/uninstall
├── references/                 # Technical documentation
├── scripts/                    # Core pipeline scripts
└── tests/                      # Unit tests (no Gemini / ffmpeg runtime)
```
