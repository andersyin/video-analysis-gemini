# Deployment Guide

## Environment Setup

This project uses placeholders instead of hardcoded personal paths. Replace them before running.

### Placeholders

| Placeholder | Meaning | Example |
|-------------|---------|---------|
| `{{PROJECT_ROOT}}` | This repo's root directory | `/home/user/video-analysis-gemini` |
| `{{MEDIA_DIR}}` | Your media assets directory | `/home/user/Media` |

### Bulk Replacement

```bash
PROJECT_ROOT=$(pwd)
MEDIA_DIR="$HOME/Media"

find . -type f \( -name "*.py" -o -name "*.sh" -o -name "*.plist" -o -name "*.md" \) -exec sed -i \
  -e "s|{{PROJECT_ROOT}}|$PROJECT_ROOT|g" \
  -e "s|{{MEDIA_DIR}}|$MEDIA_DIR|g" \
  {} \;
```

Files requiring placeholder replacement:
- `scripts/standalone_watchdog.py`
- `scripts/cross_validate.py`
- `scripts/vc_cross_acct.py`
- `scripts/vo_quality_check.py`
- `scripts/run_batch_l1.sh`
- `launchd/watchdog-wrapper.sh`
- `launchd/com.video-analysis.watchdog.plist`
- `launchd/README_watchdog_install.md`
- `references/setup_准备与归档结构.md`

## Dependencies

```bash
# Python standard library only — no pip packages needed for core scripts
# External tools:
brew install ffmpeg          # ffprobe + ffmpeg
pip install openai-whisper   # STT transcription
```

## Quick Start

See [SKILL.md](SKILL.md) for the full usage guide.

## Launchd Configuration

```bash
# Copy plist to LaunchAgents
cp launchd/com.video-analysis.watchdog.plist ~/Library/LaunchAgents/

# Load
launchctl load ~/Library/LaunchAgents/com.video-analysis.watchdog.plist
```

## Project Structure

```
video-analysis-gemini/
├── SKILL.md                    # Core skill specification
├── assets/                     # Output templates
├── experiments/                # A/B test scripts
├── launchd/                    # macOS watchdog config
├── references/                 # Technical documentation
└── scripts/                    # Core pipeline scripts
```
