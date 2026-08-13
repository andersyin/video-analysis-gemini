# Contributing to video-analysis-gemini

Thanks for your interest in contributing! This project is a Gemini-powered video analysis pipeline for extracting production techniques from short-form video content.

## Getting Started

1. Fork and clone the repo
2. Ensure Python 3.9+ is installed
3. Copy `local.env.example` to `local.env` and set `MEDIA_DIR` (do not sed-replace the repo)
4. Install external tools: `brew install ffmpeg` and `pip install openai-whisper`
5. Run `python3 scripts/check_host.py`

## Project Structure

- `scripts/` — Core Python pipeline (L1 preprocessing through L4 synthesis)
- `tests/` — Unit tests that do not need Gemini keys or ffmpeg runtime
- `references/` — Technical documentation and workflow guides
- `assets/` — Output templates for reports and comparisons
- `launchd/` — macOS watchdog install/uninstall

## Coding Conventions

- Python scripts use only the standard library (no pip dependencies for core logic)
- Paths come from `MEDIA_DIR` / `local.env` / `--archive-dir` — never hardcode personal paths and never sed-replace committed files
- Comments in Chinese are acceptable (this is a Chinese-language content analysis tool)
- Each script should have a `if __name__ == "__main__"` entry point with argparse

## Before you open a PR

```bash
python -m py_compile scripts/*.py experiments/ab_test/*.py
python scripts/validate_schema.py --check-contract-sync
python -m unittest discover -s tests -v
bash -n scripts/*.sh launchd/*.sh
shellcheck --severity=warning --format=gcc scripts/*.sh launchd/*.sh
```

Linux CI cannot run ffmpeg / Whisper / launchd / Gemini `view_file`. Do not add tests that need API keys or real video files.

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Test your changes with real video files if possible
3. Ensure no personal information (names, paths, account details, API keys) is in your code
4. Submit a PR with a clear description of what changed and why

## Reporting Issues

GitHub Issues may be disabled on this repository. Prefer a pull request, or include in any report:

- What you were trying to do
- The command you ran
- The error output
- Your Python version and OS
