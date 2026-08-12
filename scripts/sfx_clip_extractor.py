#!/usr/bin/env python3
"""
音效试听片段提取器 — 从对标原片按时间戳批量切参考音频

⚠️ 合规红线：切出的片段来自对标账号视频，仅供内部选型试听，永不进成片。
成片可用音频走 _sound_lib_v1/（实拍 + AI 生成），见音效决策台 SKILL §五。

输入: _sfx_library/sfx_library_v2.json + 各视频 _state.json 的 view_file_target
输出: _sfx_library/clips/<video_id>/<sfx_id>.m4a （aac 128k）
      _sfx_library/clips_index.json  {sfx_id: 相对路径}
切窗: 时间戳前 0.3s 起，SFX 2.3s / Ducking 3s / BGM 4s；幂等（已存在跳过）

用法:
  python3 sfx_clip_extractor.py --archive-dir /path/to/对标视频分析资产 [--workers 6] [--force]
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PRE_ROLL = 0.3


def clip_duration(entry):
    cat = entry.get("category_norm") or ""
    if cat == "背景音乐":
        return 4.0
    if cat == "音频闪避":
        return 3.0
    return 2.3


def find_video_paths(archive_dir):
    paths = {}
    for state in Path(archive_dir).glob("*/videos/*/_state.json"):
        try:
            with open(state, encoding="utf-8") as f:
                target = json.load(f).get("view_file_target")
            if target and Path(target).exists():
                paths[state.parent.name] = target
        except Exception:
            continue
    # 兜底：_state.json 缺失/target 失效时，按 "<video_id>.mp4" 在竞品研究根目录搜（不回写状态文件）
    root = Path(archive_dir).parent
    for vdir in Path(archive_dir).glob("*/videos/*"):
        vid = vdir.name
        if vid in paths or not vdir.is_dir():
            continue
        hits = [p for p in root.glob(f"*/*/{vid}.mp4") if "对标视频分析资产" not in str(p)]
        if hits:
            paths[vid] = str(hits[0])
    return paths


def extract_one(src, out_path, start, dur):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{start:.2f}", "-i", src, "-t", f"{dur:.2f}",
           "-vn", "-c:a", "aac", "-b:a", "128k", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
        return r.stderr.strip()[:150] or "输出为空/过小"
    return None


def main():
    parser = argparse.ArgumentParser(description="音效试听片段提取器")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--force", action="store_true", help="已存在也重切")
    args = parser.parse_args()

    libdir = Path(args.archive_dir) / "_sfx_library"
    clips_dir = libdir / "clips"
    with open(libdir / "sfx_library_v2.json", encoding="utf-8") as f:
        v2 = json.load(f)
    video_paths = find_video_paths(args.archive_dir)

    jobs, skipped_no_src, index = [], [], {}
    for e in v2["entries"]:
        vid = e["source_video"]
        src = video_paths.get(vid)
        rel = f"clips/{vid}/{e['sfx_id']}.m4a"
        out_path = libdir / rel
        if not src:
            skipped_no_src.append(vid)
            continue
        index[e["sfx_id"]] = rel
        if out_path.exists() and not args.force:
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        start = max(0.0, float(e.get("timestamp_sec", 0)) - PRE_ROLL)
        jobs.append((src, out_path, start, clip_duration(e), e["sfx_id"]))

    print(f"明细 {len(v2['entries'])} 条 · 有原片 {len(index)} · 本次待切 {len(jobs)} · 无原片视频 {len(set(skipped_no_src))} 个")
    errors = []
    if jobs:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(extract_one, s, o, st, d): sid for s, o, st, d, sid in jobs}
            done = 0
            for fut in as_completed(futs):
                err = fut.result()
                done += 1
                if err:
                    errors.append(f"{futs[fut]}: {err}")
                    index.pop(futs[fut], None)
                if done % 100 == 0:
                    print(f"  进度 {done}/{len(jobs)}")

    # 索引只收物理存在的；保留既有索引的其他键（如 novocals，规则 7：禁止整文件覆盖并发字段）
    index = {k: v for k, v in index.items() if (libdir / v).exists()}
    idx_path = libdir / "clips_index.json"
    existing = {}
    if idx_path.exists():
        try:
            with open(idx_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing.update({"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "note": "对标参考试听片段，仅内部选型用，永不进成片",
                     "total_clips": len(index), "clips": index})
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)

    size_mb = sum((libdir / v).stat().st_size for v in index.values()) / 1048576
    print(f"✅ 试听片段 {len(index)} 条 · {size_mb:.1f}MB · 索引 clips_index.json")
    if errors:
        print(f"⚠️ 失败 {len(errors)} 条: " + "; ".join(errors[:5]))
    if set(skipped_no_src):
        print(f"⚠️ 缺原片路径的视频: {sorted(set(skipped_no_src))[:6]}")
    sys.exit(1 if len(index) == 0 else 0)


if __name__ == "__main__":
    main()
