#!/usr/bin/env python3
"""
试听片段去人声器 — Demucs (htdemucs) 批量剥离人声，产出"干净版"参考片段

背景：2026-07-31 用户反馈试听片段混杂人声。方案=AI 音源分离，保留伴奏轨（音效+BGM）。
诚实边界：人声可去 80-95%，但 BGM 与音效在同一轨无法再分；与人声完全重叠的瞬间有残留。

输入: _sfx_library/clips/ + clips_index.json
输出: _sfx_library/clips_novocals/<video_id>/<sfx_id>.m4a
      _sfx_library/clips_index.json 增加 "novocals" 映射（与 clips 同 key）
性能: 分批调用 demucs（每批一次模型加载），MPS 加速；每批完成立即转码落盘（渐进，可中断续跑）

用法:
  python3 sfx_vocal_strip.py --archive-dir /path/to/对标视频分析资产 [--batch 80] [--device mps]
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def transcode(wav, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(out_path)],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 1024


def main():
    parser = argparse.ArgumentParser(description="试听片段去人声器")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--batch", type=int, default=80)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    libdir = Path(args.archive_dir) / "_sfx_library"
    idx_path = libdir / "clips_index.json"
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    clips = idx.get("clips", {})
    novocals = idx.get("novocals", {})

    # 待处理：有原片段但无干净版（幂等续跑）
    todo = []
    for sid, rel in clips.items():
        nv_rel = rel.replace("clips/", "clips_novocals/", 1)
        if (libdir / nv_rel).exists():
            novocals[sid] = nv_rel
            continue
        src = libdir / rel
        if src.exists():
            todo.append((sid, src, nv_rel))

    print(f"片段 {len(clips)} · 已有干净版 {len(novocals)} · 本次待处理 {len(todo)}")
    if not todo:
        idx["novocals"] = novocals
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=1)
        print("✅ 无需处理")
        return

    failed = []
    batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    for bi, batch in enumerate(batches, 1):
        with tempfile.TemporaryDirectory(prefix="demucs_sfx_") as tmp:
            cmd = ["python3", "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals",
                   "-d", args.device, "-o", tmp] + [str(src) for _, src, _ in batch]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                print(f"⚠️ 批 {bi} demucs 失败: {r.stderr.strip()[-200:]}")
                failed.extend(sid for sid, _, _ in batch)
                continue
            # 渐进落盘：本批立即转码 + 更新索引
            done = 0
            for sid, src, nv_rel in batch:
                wav = Path(tmp) / "htdemucs" / src.stem / "no_vocals.wav"
                if wav.exists() and transcode(wav, libdir / nv_rel):
                    novocals[sid] = nv_rel
                    done += 1
                else:
                    failed.append(sid)
            idx["novocals"] = novocals
            idx["novocals_note"] = "Demucs htdemucs 去人声版（保留音效+BGM 轨）；人声重叠瞬间有残留，仅选型参考"
            idx["novocals_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(idx_path, "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False, indent=1)
            print(f"批 {bi}/{len(batches)}: +{done} 落盘（累计 {len(novocals)}/{len(clips)}）")

    size_mb = sum((libdir / v).stat().st_size for v in novocals.values() if (libdir / v).exists()) / 1048576
    print(f"\n✅ 干净版 {len(novocals)}/{len(clips)} 条 · {size_mb:.1f}MB")
    if failed:
        print(f"⚠️ 失败 {len(failed)} 条: {failed[:5]}")
    sys.exit(0 if len(novocals) > 0 else 1)


if __name__ == "__main__":
    main()
