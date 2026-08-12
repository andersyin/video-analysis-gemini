# Contributing to video-analysis-gemini

Thanks for your interest in contributing! This project is a Gemini-powered video analysis pipeline for extracting production techniques from short-form video content.

## Getting Started

1. Fork and clone the repo
2. Ensure Python 3.8+ is installed
3. Install external tools: `brew install ffmpeg` and `pip install openai-whisper`
4. Run any script in `scripts/` to verify your setup

## Project Structure

- `scripts/` — Core Python pipeline (L1 preprocessing through L4 synthesis)
- `references/` — Technical documentation and workflow guides
- `assets/` — Output templates for reports and comparisons
- `launchd/` — macOS watchdog configuration for batch processing

## Coding Conventions

- Python scripts use only the standard library (no pip dependencies for core logic)
- All paths use `{{KB_BASE}}`, `{{MEDIA_DIR}}`, `{{PROJECT_ROOT}}` placeholders — never hardcode personal paths
- Comments in Chinese are acceptable (this is a Chinese-language content analysis tool)
- Each script should have a `if __name__ == "__main__"` entry point with argparse

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Test your changes with real video files if possible
3. Ensure no personal information (names, paths, account details) is in your code
4. Submit a PR with a clear description of what changed and why

## Reporting Issues

Use the Issue templates in `.github/ISSUE_TEMPLATE/`. Include:
- What you were trying to do
- The command you ran
- The error output
- Your Python version and OS
