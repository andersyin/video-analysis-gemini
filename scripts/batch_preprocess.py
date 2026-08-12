#!/usr/bin/env python3
"""
批量 L1 预处理驱动 — 提速优化建议 1（2026-07-26）

背景：L1（Whisper STT + ffprobe + 转码 + 九宫格）是纯本地 CPU 工作，可在会话外
一次性批量跑完全库，之后每个会话开局即进 L2，省去每条 1-2 分钟等待且 baseline 注入齐备。
注意：本脚本只做 L1（脚本层），不涉及任何 LLM 感知——不违反「禁止并行派发」（该禁令
针对 LLM 批量感知编造）。

跳过规则（幂等，可重复执行）：
  - 归档目录已有 _state.json 且 current_state != UNPROCESSED → 跳过
    （PREPROCESSED 及之后的任何在途/已交付状态都不重跑，保护在途分析）
  - 无 _state.json 但已有 _grounding_payload.json 含 view_file_target（新版产物）→ 跳过

用法（每账号一次调用）:
  python3 batch_preprocess.py \
    --videos-dir "/path/to/videos/AccountA" \
    --account "AccountA" \
    --archive-dir /path/to/archive \
    [--sense-threshold-mb 10] [--limit N] [--dry-run]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"}
SCRIPT_DIR = Path(__file__).resolve().parent


def find_videos(videos_dir):
    """递归枚举视频文件，按文件名排序（video_id = 文件名 stem，与 scan_helper 一致）"""
    files = [p for p in Path(videos_dir).rglob("*")
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.startswith("._")]
    return sorted(files, key=lambda p: p.name)


def skip_reason(video_dir):
    """返回跳过原因；None 表示需要预处理"""
    state_path = video_dir / "_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None  # 状态损坏 → 重跑 L1 重建
        cur = state.get("current_state", "UNPROCESSED")
        if cur != "UNPROCESSED":
            return f"state={cur}"
        return None
    payload_path = video_dir / "_grounding_payload.json"
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if "view_file_target" in payload:
            return "payload_ok(no_state)"
    return None


def main():
    parser = argparse.ArgumentParser(description="批量 L1 预处理驱动")
    parser.add_argument("--videos-dir", required=True, help="账号源视频目录（递归扫描）")
    parser.add_argument("--account", required=True, help="归档账号名")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--sense-threshold-mb", type=float, default=None,
                        help="透传给 preprocessor.py（缺省用其默认值）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=不限）")
    parser.add_argument("--dry-run", action="store_true", help="只列计划不执行")
    args = parser.parse_args()

    videos = find_videos(args.videos_dir)
    if not videos:
        print(f"⚠️ {args.videos_dir} 下未找到视频文件")
        sys.exit(1)

    account_videos_dir = Path(args.archive_dir) / args.account / "videos"
    todo, skipped = [], []
    for v in videos:
        reason = skip_reason(account_videos_dir / v.stem)
        (skipped if reason else todo).append((v, reason))

    print(f"📋 {args.account}: 共 {len(videos)} 条 | 待处理 {len(todo)} | 跳过 {len(skipped)}")
    for v, r in skipped:
        print(f"   ⏭️  {v.stem} ({r})")
    if args.limit:
        todo = todo[:args.limit]
    if args.dry_run:
        for v, _ in todo:
            print(f"   ▶️  {v.stem}")
        return

    ok, fail = 0, []
    t_batch = time.time()
    for i, (v, _) in enumerate(todo, 1):
        cmd = [sys.executable, str(SCRIPT_DIR / "preprocessor.py"),
               "--video", str(v),
               "--archive-dir", args.archive_dir,
               "--account", args.account,
               "--video-id", v.stem]
        if args.sense_threshold_mb is not None:
            cmd += ["--sense-threshold-mb", str(args.sense_threshold_mb)]
        t0 = time.time()
        print(f"\n[{i}/{len(todo)}] 🎬 {v.stem}", flush=True)
        result = subprocess.run(cmd)
        elapsed = round(time.time() - t0, 1)
        if result.returncode == 0:
            ok += 1
            print(f"   ✅ 完成（{elapsed}s）", flush=True)
        else:
            fail.append(v.stem)
            print(f"   ❌ 失败 rc={result.returncode}（{elapsed}s），继续下一条", flush=True)

    total_min = round((time.time() - t_batch) / 60, 1)
    print(f"\n{'=' * 50}\n📊 {args.account} 批量 L1 完成: 成功 {ok} / 失败 {len(fail)} / "
          f"跳过 {len(skipped)} | 耗时 {total_min} 分钟")
    if fail:
        print("❌ 失败列表: " + ", ".join(fail))
        sys.exit(2)


if __name__ == "__main__":
    main()
