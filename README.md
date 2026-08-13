# video-analysis-gemini

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![CI](https://img.shields.io/github/actions/workflow/status/andersyin/video-analysis-gemini/ci.yml)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)

> A Gemini-powered multimodal pipeline for deconstructing short-form video production techniques — from raw video to structured, queryable analysis assets.

用 Gemini 原生多模态能力对短视频进行制作技术全维度拆解的工具，通过四层流水线将视频转化为结构化、可追踪的分析资产。

---

## Why This Exists

Traditional video analysis tools give you views, likes, and engagement metrics. This tool tells you **how** a video was made: shot composition, ASL rhythm, SFX design, narrative hooks, AI generation traces, and production cost estimates — all extracted by having Gemini actually *watch* the video with audio.

## Architecture

```
Layer 1: Preprocessing (Signal Extraction)
  ├── ffprobe → hardware metadata
  ├── Whisper → millisecond-level STT
  ├── Dynamic 9-grid keyframe extraction
  └── Account baseline injection

Layer 2: Multimodal Perception (Gemini Flash)
  ├── Native audiovisual long-context viewing
  ├── 5-dimension structured JSON extraction
  └── Honesty report with evidence chains

Layer 3: QA & Adversarial Probing (Gemini Pro)
  ├── Physical gates (Schema / density / timeline)
  ├── Semantic audit (A/V sync / causal consistency)
  ├── Adversarial directed probes
  └── 3-round circuit breaker

Layer 4: Delivery & IP Asset Compilation
  ├── Final analysis_<date>.json
  ├── synthesis_engine formula extraction
  └── Auto-compiled production SOP
```

## Five Analysis Dimensions

| Dimension | What It Captures |
|-----------|-----------------|
| **cinematography** | Shot language (angles, DOF, ASL rhythm, lighting) |
| **ai_fx** | AI generation traces (consistency, lip-sync, prop fusion) |
| **audio** | Sound design (VO characteristics, SFX mapping, BGM/ducking) |
| **narrative** | Story structure (attention curve, information gap, hooks) |
| **sop** | Production SOP (complexity cost, reusable assets, monetization) |

## Quick Start

### Prerequisites

- Python 3.9+
- ffmpeg + ffprobe (`brew install ffmpeg` on macOS)
- [OpenAI Whisper](https://github.com/openai/whisper) (`pip install openai-whisper`)
- Gemini via Antigravity / `agy` for Layer 2–3 (`view_file`). This repo does **not** read `GEMINI_API_KEY` — do not commit API keys.

### Installation

```bash
git clone https://github.com/andersyin/video-analysis-gemini.git
cd video-analysis-gemini
cp local.env.example local.env   # gitignored
# edit MEDIA_DIR=/path/to/Media
python3 scripts/check_host.py
```

### Configuration

Paths come from the environment or `local.env`. **Do not sed-replace committed files.**

| Variable | Meaning | Example |
|----------|---------|---------|
| `MEDIA_DIR` | Your media / archive parent directory | `$HOME/Media` |
| `KB_BASE` | Optional watchdog heartbeat parent | `$HOME/kb` (unset → `/tmp`) |
| `PROJECT_ROOT` | Set automatically from the script location | this clone |

```bash
export MEDIA_DIR="$HOME/Media"
# or: source local.env after editing it
```

See [DEPLOY.md](DEPLOY.md) for detailed setup.

### Run Preprocessing

```bash
python3 scripts/batch_preprocess.py \
  --videos-dir "$MEDIA_DIR/AccountA" \
  --account AccountA \
  --archive-dir "$MEDIA_DIR/analysis_archive"
```

### Background Watchdog (macOS)

```bash
bash launchd/install.sh
# uninstall: bash launchd/uninstall.sh
```

Liveness is the heartbeat file mtime (`/tmp/video-analysis-watchdog.json` unless `KB_BASE` is set), not `launchctl list`.

## Supported Video Specs

| Dimension | Range | Optimal |
|-----------|-------|---------|
| Format | .mp4 .mov .webm .m4v .mkv .avi | .mp4 (H.264 + AAC) |
| Size | up to 2GB | 10MB ~ 300MB |
| Duration | 15s ~ 60min | 15s ~ 5min |
| Resolution | 360p ~ 4K | 720p ~ 1080p |
| Audio | Must have audio track | AAC clear audio |

## Key Scripts

| Script | Function | Layer |
|--------|----------|-------|
| `preprocessor.py` | Whisper STT + ffprobe + keyframe extraction | L1 |
| `session_guard.py` | State management + preflight + orphan detection | Global |
| `standalone_watchdog.py` | launchd-powered standalone watchdog | Monitor |
| `check_host.py` | First-run: Python / ffmpeg / Whisper / `MEDIA_DIR` | Setup |
| `unified_gate.py` | Schema / density / timeline hard gates | L3 |
| `pro_qa_inspector.py` | Pro semantic audit + adversarial probes | L3 |
| `synthesis_engine.py` | Cross-video formula extraction | L4 |
| `cross_validate.py` | Multi-dimensional consistency check | QA |
| `ip_sop_compiler.py` | IP-specific SOP compilation | L4 |
| `sfx_enrich.py` | SFX enrichment and pattern matching | L3 |
| `export_visualization.py` | HTML report + Obsidian canvas export | Output |

## Model Routing

| Task | Model | Why |
|------|-------|-----|
| Video perception | Gemini 3.6 Flash | Native multimodal, high throughput, low cost |
| Honesty audit + semantic QA | Gemini 3.1 Pro | Anti-hallucination, causal reasoning |
| Formula synthesis | Pro 3.1 (Agent mode) | Cross-item induction, causal chains |
| Strategic decisions | Pro 3.1 (Agent mode) | IP feature understanding |

## Anti-Skip Rules

Each layer entry must verify the previous layer's output exists:

| Entry | Prerequisite |
|-------|-------------|
| L1 | `current_state = UNPROCESSED` |
| L2 | `_grounding_payload.json` exists + `PREPROCESSED` state |
| L3 | `analysis_<date>.json` has 5 sections + state in `[FLASH_EXTRACTED, PROBE_REPAIRING, PRO_AUDITING]` |
| L4 | `_qa_result.json` exists with `qa_passed = true` + `PRO_AUDITING` state |

## Project Structure

```
video-analysis-gemini/
├── SKILL.md                    # Core skill specification (must read)
├── README.md                   # This file
├── DEPLOY.md                   # Deployment guide
├── CHANGELOG.md                # Version history
├── CONTRIBUTING.md             # Contribution guide
├── pyproject.toml              # Python project metadata
├── requirements.txt            # Dependencies (standard lib only)
├── local.env.example           # Path config template (copy to local.env)
├── tests/                      # Unit tests (no API / ffmpeg runtime)
├── assets/                     # Output templates
├── experiments/                # A/B test scripts
├── launchd/                    # macOS watchdog config
├── references/                 # Technical documentation
└── scripts/                    # Core pipeline scripts
```

## Documentation

- [SKILL.md](SKILL.md) — Full skill specification
- [DEPLOY.md](DEPLOY.md) — Deployment guide
- [CHANGELOG.md](CHANGELOG.md) — Version history
- [CONTRIBUTING.md](CONTRIBUTING.md) — How to contribute
- [references/](references/) — Technical reference docs

## License

MIT — see [LICENSE](LICENSE)

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). GitHub Issues may be disabled on this repository.
