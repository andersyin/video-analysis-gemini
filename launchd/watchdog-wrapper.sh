#!/bin/bash
# watchdog-wrapper.sh — launchd 入口（P0-4）
# 为什么要包一层 bash：本机 TCC 实测（2026-07-28）python3 直连被拦
# （即使给了 FDA），而既有外置卷 launchd 任务全部经 /bin/bash 正常运行
# （daily-work-mirror / patrol-weekly / kb-media-weekly-check 同款模式）。
exec /Library/Developer/CommandLineTools/usr/bin/python3 \
  "{{PROJECT_ROOT}}/scripts/standalone_watchdog.py" \
  --archive-dir "{{MEDIA_DIR}}/analysis_archive" \
  --auto-finalize
