#!/usr/bin/env python3
"""扫描辅助脚本 —— 不调用任何 API，仅负责目录列举与归档结构准备。

负责：
1. 列出视频目录中所有视频文件
2. 创建归档目录结构
3. 提取视频元数据（时长、分辨率、帧率，需 ffprobe）
4. 生成/更新账号元数据快照
5. 生成扫描日志模板（Agent 手动填充分析结果）

用法:
  # 列出视频并创建归档结构
  python scan_helper.py --videos-dir /path/to/videos \
    --account "AccountD" --platform "TikTok" \
    --archive-dir /path/to/archive

  # 增量模式（跳过已归档视频）
  python scan_helper.py --videos-dir /path/to/videos \
    --account "AccountD" --archive-dir /path/to/archive --incremental
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"}


def find_videos(videos_dir):
    """找出目录下所有视频文件（递归搜索子目录），按文件名排序。

    支持两种传入方式：
    - 具体视频子目录（如 2026-07-21-TikTokTop15/）→ 搜索该层
    - 账号根目录（如 AccountA/）→ 递归搜索所有子目录
    """
    d = Path(videos_dir)
    if not d.is_dir():
        sys.exit(f"错误：视频目录不存在: {videos_dir}")
    videos = sorted(
        [f for f in d.rglob("*") if f.suffix.lower() in VIDEO_EXTS and f.is_file()],
        key=lambda x: x.name,
    )
    return videos


def get_analyzed_video_ids(archive_dir, account):
    """获取已分析过的视频ID集合（用于增量扫描）。"""
    account_dir = Path(archive_dir) / account / "videos"
    if not account_dir.exists():
        return set()
    return {d.name for d in account_dir.iterdir() if d.is_dir()}


def detect_silence_points(video_path, min_silence_sec=0.5):
    """用 ffmpeg silencedetect 检测静音点，返回静音起始时间列表。"""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", str(video_path),
                "-af", f"silencedetect=d={min_silence_sec}:m=-30dB",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=60,
        )
        # 解析 stderr 中的 silence_start 行
        starts = []
        for line in result.stderr.split("\n"):
            m = re.search(r"silence_start: ([\d.]+)", line)
            if m:
                starts.append(float(m.group(1)))
        return starts
    except Exception:
        return []


def smart_split_video(video_path, metadata, max_segment_sec=300):
    """对长视频进行智能切片，返回分段信息列表。

    策略：优先在静音点切分，若无静音点则按 max_segment_sec 均分。
    返回 [{"part": 1, "start_sec": 0, "end_sec": 120, "duration_sec": 120}, ...]
    """
    duration = metadata.get("duration_sec", 0)
    if duration <= 0 or duration <= max_segment_sec:
        return [{"part": 1, "start_sec": 0, "end_sec": duration, "duration_sec": duration}]

    # 检测静音点作为自然切分位置
    silence_points = detect_silence_points(video_path)

    # 在静音点中选取合适的切分位置
    cut_points = [0.0]
    for sp in silence_points:
        if sp > 10 and sp < duration - 10 and sp - cut_points[-1] > 60:
            cut_points.append(sp)
    cut_points.append(float(duration))

    # 如果静音点不足以将视频切成 ≤max_segment_sec 的段，补充均匀切分
    segments = []
    for i in range(len(cut_points) - 1):
        seg_dur = cut_points[i + 1] - cut_points[i]
        if seg_dur <= max_segment_sec:
            segments.append((cut_points[i], cut_points[i + 1]))
        else:
            # 均匀切分超长段
            n = int(seg_dur // max_segment_sec) + 1
            step = seg_dur / n
            for j in range(n):
                s = cut_points[i] + j * step
                e = min(cut_points[i] + (j + 1) * step, cut_points[i + 1])
                segments.append((s, e))

    return [
        {
            "part": i + 1,
            "start_sec": round(s, 1),
            "end_sec": round(e, 1),
            "duration_sec": round(e - s, 1),
        }
        for i, (s, e) in enumerate(segments)
    ]


def extract_video_metadata(video_path):
    """用 ffprobe 提取视频元数据（时长、分辨率、帧率）。无 ffprobe 则返回空。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(video_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
        astream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        return {
            "duration_sec": round(float(fmt.get("duration", 0)), 1),
            "width": int(vstream.get("width", 0)),
            "height": int(vstream.get("height", 0)),
            "fps": vstream.get("r_frame_rate", ""),
            "video_codec": vstream.get("codec_name", ""),
            "audio_codec": astream.get("codec_name", ""),
            "file_size_mb": round(float(fmt.get("size", 0)) / (1024 * 1024), 1),
        }
    except Exception:
        return {}


def update_account_meta(archive_dir, account, platform, video_count, ip_context, model):
    """更新账号元数据快照。"""
    meta_path = Path(archive_dir) / account / "_account_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    meta = {"account": account, "platform": platform, "snapshots": []}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "video_count": video_count,
        "model": model,
        "ip_context": ip_context or "",
        "mode": "gemini-native-multimodal",
    }
    meta.setdefault("snapshots", []).append(snapshot)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def init_scan_log(archive_dir, account, model, sections):
    """初始化/获取扫描日志，返回今日 scan 记录引用。"""
    log_path = Path(archive_dir) / account / "_scan_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    log = {"account": account, "scans": []}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # 查找今日记录
    today_scan = None
    for scan in log.get("scans", []):
        if scan.get("date") == date_str:
            today_scan = scan
            break

    if today_scan is None:
        today_scan = {
            "date": date_str,
            "model": model,
            "mode": "gemini-native-multimodal",
            "sections": sections,
            "videos": [],
            "failed": [],
        }
        log.setdefault("scans", []).append(today_scan)

    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def upsert_index(archive_dir, account, **fields):
    """更新全局账号索引 <archive-dir>/_index.json（preprocessor baseline 注入读此文件）。

    只做增量合并：仅覆盖传入的 fields，其他账号与其他字段原样保留。
    常用 fields: platform, video_count, analyzed_count, asl_mean, formula_name
    """
    index_path = Path(archive_dir) / "_index.json"
    index = {"accounts": {}}
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    acct = index.setdefault("accounts", {}).setdefault(account, {})
    acct.update({k: v for k, v in fields.items() if v is not None})
    acct["updated"] = datetime.now().strftime("%Y-%m-%d")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def main():
    parser = argparse.ArgumentParser(
        description="扫描辅助脚本（不调 API · 列举视频 · 创建归档结构 · 生成元数据）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--videos-dir", help="视频文件所在目录（支持账号根目录，递归搜索子目录）")
    parser.add_argument("--account", required=True, help="账号名")
    parser.add_argument("--platform", default="", help="平台（如 TikTok/抖音/B站/YouTube）")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--model", default="gemini-3.6-flash", help="使用的模型标识（仅用于元数据记录）")
    parser.add_argument("--ip-context", default="", help="自有IP上下文")
    parser.add_argument("--incremental", action="store_true", help="增量模式：跳过已归档视频")
    parser.add_argument("--smart-split", action="store_true", help="对 >5min 长视频按静音/转场智能切片，输出分段映射表")
    parser.add_argument("--max-segment-sec", type=int, default=300, help="智能切片最大段时长（秒，默认 300=5min）")
    parser.add_argument("--init-account", action="store_true",
                        help="轻量初始化：不扫视频，只建 _account_meta.json + _scan_log.json + upsert _index.json（单视频流程的 Layer 1 前置）")
    parser.add_argument("--cleanup-sense", action="store_true",
                        help="清理已交付(PASS_DELIVERED)视频的过程文件（_sense.mp4/_sense_audio.m4a/_pro_review_packet.json/过期Whisper原始JSON），默认 dry-run 仅预览")
    parser.add_argument("--video-id", default="",
                        help="配合 --cleanup-sense 限定单视频（链尾即焚用；省略则扫全账号 PASS_DELIVERED）")
    parser.add_argument("--apply", action="store_true",
                        help="配合 --cleanup-sense 实际执行（不加则仅列出可释放空间）")
    parser.add_argument("--quarantine-dir", default="",
                        help="隔离区目录：指定后 --apply 改为移动到 <quarantine-dir>/<date>/<account>/<video-id>/ 而非删除（可逆，推荐）")
    args = parser.parse_args()

    # ── 过程文件清理模式：只清 PASS_DELIVERED 状态，防误删在途分析 ──
    if args.cleanup_sense:
        import shutil as _shutil
        from datetime import datetime as _dt
        videos_root = Path(args.archive_dir) / args.account / "videos"
        targets = ["_sense.mp4", "_sense_audio.m4a", "_pro_review_packet.json"]
        candidates, freed_bytes = [], 0
        if videos_root.is_dir():
            for vdir in sorted(videos_root.iterdir()):
                if not vdir.is_dir():
                    continue
                # P1-3：--video-id 限定单视频（链尾即焚用，锁定影响面到当前交付视频）
                if getattr(args, "video_id", "") and vdir.name != args.video_id:
                    continue
                state_file = vdir / "_state.json"
                state = {}
                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        pass
                if state.get("current_state") != "PASS_DELIVERED":
                    continue
                # 过期 Whisper 原始输出：<片名>.json（与视频目录同名，内容已并入 grounding payload）
                stale = []
                whisper_raw = vdir / f"{vdir.name}.json"
                if whisper_raw.exists():
                    stale.append(whisper_raw.name)
                for name in targets + stale:
                    f = vdir / name
                    if f.exists():
                        size = f.stat().st_size
                        dest = ""
                        candidates.append({
                            "video_id": vdir.name, "file": name,
                            "size_mb": round(size / 1024 / 1024, 2),
                        })
                        freed_bytes += size
                        if args.apply:
                            if args.quarantine_dir:
                                qdir = (Path(args.quarantine_dir) / _dt.now().strftime("%Y-%m-%d")
                                        / args.account / vdir.name)
                                qdir.mkdir(parents=True, exist_ok=True)
                                dest = str(qdir / name)
                                _shutil.move(str(f), dest)
                                candidates[-1]["moved_to"] = dest
                            else:
                                f.unlink()
        result = {
            "mode": "cleanup-sense",
            "applied": bool(args.apply),
            "quarantine": args.quarantine_dir or None,
            "scope": str(videos_root),
            "total_files": len(candidates),
            "total_freed_mb": round(freed_bytes / 1024 / 1024, 1),
            "candidates": candidates,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.apply and args.quarantine_dir:
            verb = f"🧹 已移至隔离区 {args.quarantine_dir}"
        elif args.apply:
            verb = "🧹 已删除"
        else:
            verb = "🔍 DRY-RUN（加 --apply 执行；加 --quarantine-dir 移动而非删除）"
        sys.stderr.write(
            f"{verb}: {len(candidates)} 个过程文件，可释放 {round(freed_bytes / 1024 / 1024, 1)}MB\n"
        )
        return

    # ── 轻量初始化模式：只建账，不扫视频 ──
    if args.init_account:
        sections = ["cinematography", "ai_fx", "audio", "narrative", "sop"]
        account_dir = Path(args.archive_dir) / args.account
        (account_dir / "videos").mkdir(parents=True, exist_ok=True)
        log_path = init_scan_log(args.archive_dir, args.account, args.model, sections)
        meta_path = update_account_meta(
            args.archive_dir, args.account, args.platform, 0, args.ip_context, args.model,
        )
        index_path = upsert_index(
            args.archive_dir, args.account,
            platform=args.platform or "unknown",
            video_count=0,
        )
        result = {
            "mode": "init-account",
            "account": args.account,
            "scan_log": str(log_path),
            "account_meta": str(meta_path),
            "index": str(index_path),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.stderr.write(f"✅ 账号账簿初始化完成: {args.account}\n")
        return

    if not args.videos_dir:
        parser.error("扫描视频必须提供 --videos-dir（或使用 --init-account 仅建账）")

    videos = find_videos(args.videos_dir)
    if not videos:
        sys.exit(f"错误：目录中未找到视频文件: {args.videos_dir}")

    # 增量扫描
    analyzed = get_analyzed_video_ids(args.archive_dir, args.account) if args.incremental else set()
    new_videos = [v for v in videos if v.stem not in analyzed]
    skipped = len(videos) - len(new_videos)

    # 创建归档目录
    account_dir = Path(args.archive_dir) / args.account
    videos_dir = account_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    # 初始化扫描日志
    sections = ["cinematography", "ai_fx", "audio", "narrative", "sop"]
    log_path = init_scan_log(args.archive_dir, args.account, args.model, sections)

    # 更新账号元数据
    meta_path = update_account_meta(
        args.archive_dir, args.account, args.platform,
        len(new_videos), args.ip_context, args.model,
    )

    # 更新全局账号索引（preprocessor baseline 注入读取此文件）
    index_path = upsert_index(
        args.archive_dir, args.account,
        platform=args.platform or "unknown",
        video_count=len(videos),
    )

    # 为每条新视频创建目录并提取元数据
    video_entries = []
    for video in new_videos:
        video_id = video.stem
        video_archive_dir = videos_dir / video_id
        video_archive_dir.mkdir(parents=True, exist_ok=True)

        # 提取元数据
        metadata = extract_video_metadata(video)
        if metadata:
            meta_file = video_archive_dir / "_video_meta.json"
            meta_file.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        # 智能切片（仅对长视频）
        segments = None
        if args.smart_split and metadata.get("duration_sec", 0) > args.max_segment_sec:
            segments = smart_split_video(video, metadata, args.max_segment_sec)
            seg_file = video_archive_dir / "_segments.json"
            seg_file.write_text(
                json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            sys.stderr.write(f"  📐 {video.name}: 智能切片为 {len(segments)} 段\n")

        video_entries.append({
            "index": len(video_entries) + 1,
            "video_id": video_id,
            "filename": video.name,
            "path": str(video),
            "archive_dir": str(video_archive_dir),
            "output_file": str(video_archive_dir / f"analysis_{datetime.now().strftime('%Y-%m-%d')}.json"),
            "metadata": metadata,
            "segments": segments,
        })

    # 输出 JSON 供 Agent 解析
    result = {
        "mode": "gemini-native-multimodal",
        "account": args.account,
        "platform": args.platform,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_videos": len(videos),
        "skipped": skipped,
        "to_analyze": len(new_videos),
        "archive_dir": str(account_dir),
        "scan_log": str(log_path),
        "account_meta": str(meta_path),
        "index": str(index_path),
        "prompts_file": str(Path(__file__).resolve().parent / "prompts.json"),
        "sections": sections,
        "videos": video_entries,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.stderr.write(
        f"\n{'=' * 60}\n"
        f"扫描辅助完成\n"
        f"{'=' * 60}\n"
        f"总视频: {len(videos)} | 跳过: {skipped} | 待分析: {len(new_videos)}\n"
        f"归档目录: {account_dir}\n"
        f"扫描日志: {log_path}\n"
        f"提示词文件: {result['prompts_file']}\n"
        f"\n下一步：Agent 逐条观看视频，应用 prompts.json 中的 5 板块提示词，\n"
        f"将结果保存到每条视频的 output_file 路径。\n"
    )


if __name__ == "__main__":
    main()
