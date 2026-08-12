#!/usr/bin/env python3
"""兼容入口 — 正式版已迁移至 scripts/ab_compare.py（2026-07-26）。

旧版本存在等值误判 bug：`"A" if a>b else "B"` 在平局时默认判 B。
正式版统一 _winner() 三路判定，并支持 --json-out 供回归脚本消费。
本文件仅转发参数到正式版，避免双份维护漂移。
"""
import os
import subprocess
import sys

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "ab_compare.py")

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, _SCRIPT] + sys.argv[1:]))
