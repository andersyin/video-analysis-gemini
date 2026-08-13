#!/usr/bin/env python3
"""
Layer 1 预处理器 — 信号显性化预处理模块

功能：
  1. ffprobe 提取硬指标元数据（时长/分辨率/帧率/编码）
  2. 大文件感知专用转码（>10MB 自动生成 _sense.mp4 + _sense_audio.m4a，
     防 view_file 上传 broken pipe / connection reset）
  3. Whisper 提取毫秒级时间戳台词 Ground Truth（STT）
  4. 动态九宫格卡点切帧图（始终生成）
  5. 注入账号 Baseline

用法:
  python3 preprocessor.py \
    --video /path/to/video.mp4 \
    --archive-dir /path/to/archive \
    --account "AccountD" \
    --video-id "TOP01_xxxx" \
    [--sense-threshold-mb 10] [--no-sense]

产出:
  <archive-dir>/<account>/videos/<video-id>/_grounding_payload.json
  <archive-dir>/<account>/videos/<video-id>/_video_meta.json (如果不存在)
  <archive-dir>/<account>/videos/<video-id>/_sense.mp4 (如果原文件 > 阈值)
  <archive-dir>/<account>/videos/<video-id>/_sense_meta.json (感知轨的 ffprobe 元数据)
  <archive-dir>/<account>/videos/<video-id>/_sense_audio.m4a (独立音轨，降级资产)
  <archive-dir>/<account>/videos/<video-id>/_contact_sheet.jpg (始终生成)
  <archive-dir>/<account>/videos/<video-id>/_state.json (状态机)
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from local_paths import resolve_tool

FFPROBE = resolve_tool("ffprobe")
FFMPEG = resolve_tool("ffmpeg")
WHISPER = resolve_tool("whisper")

# 感知专用转码默认阈值（MB）。根因诊断（2026-07-26 堆栈分析）：
# 视频经 view_file 放入请求体时 base64 膨胀 ~1.33x（54.2MB → ~72MB body），
# 本地 Sidecar（127.0.0.1:12450）拒收超大 Request Body 主动断管，
# 触发 write: broken pipe（上传阶段）/ read: connection reset（等待响应阶段）。
# 2026-07-26 提速优化：阈值由 20MB 降至 10MB——一次 broken pipe 的代价是整段 L2（45-70min）
# 重来，而转码已验证不伤感知（保完整音视频流），更小请求体进一步压低上传失败率与传输耗时。
DEFAULT_SENSE_THRESHOLD_MB = 10

# 两档转码参数：第一档画质优先；若产物仍超阈值则升级到第二档
# 注意 scale 必须同时约束宽和高：只写 min(1280,iw):-2 对竖屏视频（1080x1920）不缩放
SENSE_TIERS = [
    {"scale_w": 1280, "scale_h": 720, "crf": "30", "preset": "superfast",
     "audio_bitrate": "96k", "max_fps": None},
    {"scale_w": 960, "scale_h": 540, "crf": "34", "preset": "superfast",
     "audio_bitrate": "64k", "max_fps": 30},
]


def run_ffprobe(video_path):
    """运行 ffprobe 提取视频元数据"""
    cmd = [
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
            astream = next((s for s in streams if s.get("codec_type") == "audio"), {})
            meta = {
                "duration_sec": float(vstream.get("duration", 0) or data.get("format", {}).get("duration", 0)),
                "width": int(vstream.get("width", 0)),
                "height": int(vstream.get("height", 0)),
                "fps": vstream.get("r_frame_rate", "0/1"),
                "video_codec": vstream.get("codec_name", "unknown"),
                "audio_codec": astream.get("codec_name", "unknown"),
                "file_size_mb": round(os.path.getsize(video_path) / 1024 / 1024, 1),
            }
            return meta
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"⚠️ ffprobe failed: {e}")
    return None


def _probe_quick(video_path):
    """轻量 ffprobe，只取时长与尺寸（用于感知轨产物校验）"""
    cmd = [
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
            return {
                "duration_sec": float(vstream.get("duration", 0) or data.get("format", {}).get("duration", 0)),
                "width": int(vstream.get("width", 0)),
                "height": int(vstream.get("height", 0)),
                "file_size_mb": round(os.path.getsize(video_path) / 1024 / 1024, 1),
            }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def extract_audio_track(video_path, video_dir, meta, audio_bitrate="96k"):
    """提取独立音轨 `_sense_audio.m4a`（音视解耦降级资产）。

    用途：
    - 紧急降级模式：_sense.mp4 仍传输失败时，音频(2~3MB) + 九宫格组合感知
    - 音频体积极小，传输成功率 ~100%，且 Gemini 原生支持音频感知
    源视频无音频轨时返回 None（不视为错误）。
    """
    if meta.get("audio_codec", "unknown") in (None, "", "unknown"):
        print("   ℹ️ 源视频无音频轨，跳过音轨提取")
        return None
    audio_path = os.path.join(video_dir, "_sense_audio.m4a")
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vn", "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and os.path.exists(audio_path):
            size_mb = round(os.path.getsize(audio_path) / 1024 / 1024, 1)
            print(f"   ✅ 降级音轨: {audio_path}（{size_mb}MB）")
            return audio_path
        print(f"   ⚠️ 音轨提取失败: {result.stderr[-200:]}")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"   ⚠️ 音轨提取失败: {e}")
    return None


def transcode_sense(video_path, video_dir, meta, threshold_mb=DEFAULT_SENSE_THRESHOLD_MB):
    """大文件感知专用转码：压缩请求体以防 view_file 上传被 Sidecar 断管。

    设计原则：
    - 不是抽帧降级——产物保留完整画面流 + 完整音频轨 + 原始时长，
      view_file 仍可全量音视频同感（Gemini 感知对 720p/96k 完全足够）。
    - 两档递进：720p/CRF30/AAC96k → 若仍超阈值 → 540p/CRF34/AAC64k/fps30。
    - 时长校验：产物时长与原片偏差 >1s 视为转码异常，弃用并重试下一档。
    - 同步提取 `_sense_audio.m4a` 独立音轨，作为音视解耦降级资产。

    返回 sense 信息 dict（写入 grounding payload），无需转码时返回 None。
    """
    src_size_mb = round(os.path.getsize(video_path) / 1024 / 1024, 1)
    if src_size_mb <= threshold_mb:
        return None

    print(f"   ⚠️ 原文件 {src_size_mb}MB > 阈值 {threshold_mb}MB（base64 膨胀后 ~{round(src_size_mb * 1.33)}MB 请求体），生成感知专用转码...")
    sense_path = os.path.join(video_dir, "_sense.mp4")
    src_duration = float(meta.get("duration_sec", 0) or 0)

    for tier_idx, tier in enumerate(SENSE_TIERS, start=1):
        vf = (
            f"scale='min(iw,{tier['scale_w']})':'min(ih,{tier['scale_h']})'"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2"
        )
        if tier["max_fps"]:
            vf += f",fps={tier['max_fps']}"
        cmd = [
            FFMPEG, "-y", "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", tier["preset"], "-crf", tier["crf"],
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", tier["audio_bitrate"],
            "-movflags", "+faststart",
            sense_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except FileNotFoundError:
            print("   ⚠️ ffmpeg 不可用，跳过感知转码（大文件直传有断管风险）")
            return None
        except subprocess.TimeoutExpired:
            print("   ⚠️ 感知转码超时（>30min），跳过")
            return None

        if result.returncode != 0 or not os.path.exists(sense_path):
            print(f"   ⚠️ 第 {tier_idx} 档转码失败: {result.stderr[-300:]}")
            continue

        sense_meta = _probe_quick(sense_path) or {}
        sense_size_mb = sense_meta.get("file_size_mb", 0)
        sense_duration = float(sense_meta.get("duration_sec", 0) or 0)

        # 时长完整性校验（±1s）
        if src_duration > 0 and abs(sense_duration - src_duration) > 1.0:
            print(f"   ⚠️ 产物时长 {sense_duration:.1f}s 与原片 {src_duration:.1f}s 偏差 >1s，重试下一档")
            continue

        if sense_size_mb > threshold_mb and tier_idx < len(SENSE_TIERS):
            print(f"   ⚠️ 第 {tier_idx} 档产物 {sense_size_mb}MB 仍超阈值，升级到第 {tier_idx + 1} 档...")
            continue

        # 转码成功 → 同步提取独立音轨（降级资产）
        audio_path = extract_audio_track(video_path, video_dir, meta)

        sense_meta_path = os.path.join(video_dir, "_sense_meta.json")
        with open(sense_meta_path, "w") as f:
            json.dump(sense_meta, f, ensure_ascii=False, indent=2)
        ratio = round(sense_size_mb / src_size_mb * 100) if src_size_mb else 0
        print(f"   ✅ 感知转码: {sense_path}（{src_size_mb}MB → {sense_size_mb}MB，{ratio}%）")
        return {
            "generated": True,
            "path": sense_path,
            "meta_path": sense_meta_path,
            "audio_path": audio_path,
            "original_size_mb": src_size_mb,
            "sense_size_mb": sense_size_mb,
            "reason": f"file_size {src_size_mb}MB > threshold {threshold_mb}MB",
            "tier": tier_idx,
            "params": {
                "max_resolution": f"{tier['scale_w']}x{tier['scale_h']}",
                "crf": tier["crf"],
                "preset": tier["preset"],
                "audio": f"aac {tier['audio_bitrate']}",
                "max_fps": tier["max_fps"],
            },
            "duration_check": "pass",
        }

    # 所有档位失败
    if os.path.exists(sense_path):
        os.remove(sense_path)
    print("   ❌ 感知转码全部档位失败，回退为原文件直传（有断管风险，建议手动压缩）")
    return None


def detect_scene_cuts(video_path, threshold=0.35):
    """算法切点锚点（2026-07-27）：ffmpeg scene 检测硬切点数，作为 shot_timeline 量级的物理参照

    背景：A/B 实验 02 号暴露欠切——mid 档 ASL 3-8s 规则误导模型对快切视频合并镜头
    （66 镜 vs 算法实测 ~185 切点）。与 _system_boundary 同一设计哲学：用算法事实压住偷懒。
    注意：scene 检测对闪光/大运动会过检，仅作量级参照（门禁层软告警），不替代感知。
    """
    cmd = [FFMPEG, "-i", video_path,
           "-vf", f"select='gt(scene,{threshold})',metadata=print", "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        count = (result.stderr or "").count("scene_score")
        return {"hard_cuts_detected": count, "threshold": threshold,
                "note": "仅作 shot_timeline 量级参照，不替代多模态感知"}
    except (subprocess.TimeoutExpired, OSError):
        return None


def run_whisper(video_path, archive_dir):
    """运行 Whisper 提取带时间戳的台词"""
    # 尝试多种 Whisper 实现
    whisper_cmds = [
        [WHISPER, video_path, "--model", "base", "--output_format", "json", "--output_dir", archive_dir],
        [sys.executable, "-m", "whisper", video_path, "--model", "base", "--output_format", "json", "--output_dir", archive_dir],
    ]

    for cmd in whisper_cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                # 查找输出 JSON
                base = Path(video_path).stem
                srt_json = Path(archive_dir) / f"{base}.json"
                if srt_json.exists():
                    with open(srt_json) as f:
                        data = json.load(f)
                    segments = data.get("segments", [])
                    stt = [
                        {
                            "start_sec": round(s["start"], 2),
                            "end_sec": round(s["end"], 2),
                            "text": s["text"].strip(),
                        }
                        for s in segments
                    ]
                    # 清理 Whisper 原始输出（内容已并入 payload，无下游消费者，防滞留）
                    try:
                        srt_json.unlink()
                    except OSError:
                        pass
                    return stt
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"⚠️ Whisper attempt failed: {e}")
            continue

    print("⚠️ Whisper not available — STT Ground Truth will be empty (Flash must do manual transcription)")
    return []


def _parse_fps(fps_str):
    """解析 '30/1' 形式的帧率字符串为浮点数"""
    try:
        num, den = fps_str.split("/")
        den = float(den)
        return float(num) / den if den else 0.0
    except (ValueError, AttributeError, ZeroDivisionError):
        return 0.0


def generate_contact_sheet(video_path, archive_dir, meta=None, grid_size=3):
    """生成九宫格拼接切片图（视觉对齐/Pro 抽查辅助）。

    精确等距抽 9 帧：用 select='eq(n,A)+eq(n,B)...' 显式指定 9 个帧序号，
    避免 fps 滤镜因 PTS 舍入/关键帧间隔产出 8 或 10 帧导致网格残缺。
    duration < 1s 时兜底跳过。
    """
    output_path = os.path.join(archive_dir, "_contact_sheet.jpg")

    meta = meta or {}
    duration = float(meta.get("duration_sec", 0) or 0)
    fps = _parse_fps(str(meta.get("fps", ""))) or 30.0
    if duration < 1.0:
        print(f"   ℹ️ 视频时长 {duration:.2f}s < 1s，跳过九宫格生成")
        return None

    total_frames = max(9, int(duration * fps))
    indices = [int(i * total_frames / 9) for i in range(9)]
    select_expr = "select='{}'".format("+".join(f"eq(n\\,{i})" for i in indices))

    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vf", f"{select_expr},scale=320:180,tile={grid_size}x{grid_size}",
        "-frames:v", "1", "-vsync", "vfr", output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        print(f"⚠️ Contact sheet generation failed: {result.stderr[-300:]}")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"⚠️ Contact sheet generation failed: {e}")
    return None


def get_account_baseline(archive_dir, account):
    """提取账号历史统计作为 Baseline"""
    index_path = os.path.join(archive_dir, "_index.json")
    if os.path.exists(index_path):
        with open(index_path) as f:
            index = json.load(f)
        acct = index.get("accounts", {}).get(account, {})
        return {
            "platform": acct.get("platform", "unknown"),
            "video_count": acct.get("video_count", 0),
            "analyzed_count": acct.get("analyzed_count", 0),
            "historical_asl_mean": acct.get("asl_mean"),
            "historical_formula": acct.get("formula_name"),
        }
    return {"platform": "unknown", "video_count": 0, "analyzed_count": 0}


def update_state(archive_dir, account, video_id, new_state, extra=None):
    """更新视频分析状态机"""
    state_path = os.path.join(archive_dir, account, "videos", video_id, "_state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)

    state["current_state"] = new_state
    state.setdefault("history", []).append({
        "state": new_state,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    })
    if extra:
        state.update(extra)

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return state


def main():
    parser = argparse.ArgumentParser(description="Layer 1 预处理器 — 信号显性化")
    parser.add_argument("--video", required=True, help="视频文件路径")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", required=True, help="账号名")
    parser.add_argument("--video-id", required=True, help="视频ID")
    parser.add_argument("--sense-threshold-mb", type=float, default=DEFAULT_SENSE_THRESHOLD_MB,
                        help=f"感知专用转码阈值（MB，默认 {DEFAULT_SENSE_THRESHOLD_MB}）")
    parser.add_argument("--no-sense", action="store_true",
                        help="禁用感知转码（强制原文件直传 view_file，有断管风险）")
    args = parser.parse_args()

    video_path = args.video
    video_dir = os.path.join(args.archive_dir, args.account, "videos", args.video_id)
    os.makedirs(video_dir, exist_ok=True)

    print("=" * 60)
    print(f"Layer 1 预处理")
    print(f"视频: {video_path}")
    print(f"归档: {video_dir}")
    print("=" * 60)

    # 1. ffprobe 元数据
    print("\n1. ffprobe 元数据提取...")
    meta = run_ffprobe(video_path)
    if meta:
        meta_path = os.path.join(video_dir, "_video_meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"   ✅ {meta}")
    else:
        print("   ❌ ffprobe 失败")
        meta = {"duration_sec": 0, "width": 0, "height": 0}

    # 1.5 大文件感知专用转码（防 view_file 上传 broken pipe / connection reset）
    print("\n1.5 感知专用转码检查...")
    sense_info = None
    if args.no_sense:
        print("   ℹ️ --no-sense 已指定，跳过感知转码")
    else:
        sense_info = transcode_sense(
            video_path, video_dir, meta,
            threshold_mb=args.sense_threshold_mb,
        )
        if not sense_info:
            size_mb = meta.get("file_size_mb", 0)
            print(f"   ✅ 无需转码（{size_mb}MB ≤ {args.sense_threshold_mb}MB 或转码不可用）")

    # view_file 实际应该加载的文件（有感知轨用感知轨，无则用原文件）
    view_file_target = sense_info["path"] if sense_info else video_path

    # 2. Whisper STT（始终对原文件执行，保音频保真度）
    print("\n2. Whisper STT 台词提取...")
    stt = run_whisper(video_path, video_dir)
    print(f"   {'✅' if stt else '⚠️'} {len(stt)} 句台词")

    # 3. 九宫格切帧（始终生成：精确等距 9 帧，辅助 Pro 抽查视觉对齐）
    #    有感知轨时从感知轨切帧——与 view_file 所见画面严格一致
    contact_sheet_path = None
    print("\n3. 九宫格切帧图...")
    contact_sheet_path = generate_contact_sheet(view_file_target, video_dir, meta)
    if contact_sheet_path:
        print(f"   ✅ {contact_sheet_path}")
    else:
        print("   ⚠️ 跳过（ffmpeg 不可用/失败或视频过短）")

    # 4. 账号 Baseline
    print("\n4. 账号 Baseline 提取...")
    baseline = get_account_baseline(args.archive_dir, args.account)
    # 分级告警：全新账号首条 → Info；账号有分析记录但 _index.json 缺失 → Warning
    if baseline.get("platform") == "unknown" and not baseline.get("analyzed_count"):
        index_path = os.path.join(args.archive_dir, "_index.json")
        analyzed_dirs = []
        videos_root = os.path.join(args.archive_dir, args.account, "videos")
        if os.path.isdir(videos_root):
            analyzed_dirs = [d for d in os.listdir(videos_root)
                             if os.path.isdir(os.path.join(videos_root, d))]
        if analyzed_dirs and not os.path.exists(index_path):
            print(f"   ⚠️ 账号已有 {len(analyzed_dirs)} 条分析记录但 _index.json 缺失，baseline 为 unknown")
            print(f"      建议先跑: python3 scan_helper.py --init-account --account {args.account} --archive-dir {args.archive_dir}")
        elif not analyzed_dirs:
            print("   ℹ️ 全新账号首条分析，baseline 为空属正常（交付后 _index.json 会自动回写）")
    print(f"   ✅ {baseline}")

    # 5. 物理锚点（_system_boundary）：封死超时长幻觉的硬基线（2026-07-26 新增）
    # LLM 缺乏物理时间流逝感，历史 A/B 测试中裸 prompt 路径曾幻觉出 39s 不存在的时间轴。
    # 此对象随 prompt_header 强制注入每个板块/每个 Subagent，并由 session_guard 在绑定点硬截断。
    duration = float(meta.get("duration_sec", 0) or 0)
    fps_raw = str(meta.get("fps", ""))
    try:
        num, _, den = fps_raw.partition("/")
        fps_val = round(float(num) / float(den or 1), 2)
    except (ValueError, ZeroDivisionError):
        fps_val = None
    system_boundary = {
        "strict_duration_sec": duration,
        "strict_fps": fps_val,
        "total_frames": int(duration * fps_val) if (duration and fps_val) else None,
        "time_range_rule": (
            f"ALL timestamps MUST be strictly within [0.00, {duration}]. "
            f"Any timestamp exceeding {duration} will be HARD REJECTED by the gate."
        ),
    }

    # 5.5 算法切点锚点（在感知轨上算，体积小速度快；无感知轨则用原文件）
    print("5.5 算法切点锚点检测...")
    scene_src = view_file_target if os.path.exists(view_file_target) else video_path
    scene_est = detect_scene_cuts(scene_src)
    if scene_est:
        print(f"   ✅ 硬切点 ~{scene_est['hard_cuts_detected']} 个 (scene>{scene_est['threshold']})")
    else:
        print("   ⚠️ 切点检测失败，跳过（不阻断）")

    # 6. 组装 Grounding Payload
    payload = {
        "_system_boundary": system_boundary,
        "_scene_cut_estimate": scene_est,
        "whisper_stt": stt,
        "ffprobe_meta": meta,
        "contact_sheet_path": contact_sheet_path,
        "account_baseline": baseline,
        "sense": sense_info,
        "view_file_target": view_file_target,
    }

    payload_path = os.path.join(video_dir, "_grounding_payload.json")
    with open(payload_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Grounding Payload 已保存: {payload_path}")

    # 7. 更新状态机
    update_state(args.archive_dir, args.account, args.video_id, "PREPROCESSED", {
        "grounding_payload": payload_path,
        "view_file_target": view_file_target,
    })
    print(f"✅ 状态更新: UNPROCESSED -> PREPROCESSED")

    # 8. 输出给 Layer 2 的指令
    print("\n" + "=" * 60)
    print("Layer 1 完成。Layer 2 指令：")
    print(f"  view_file 观看视频: {view_file_target}")
    if sense_info:
        print(f"  ⚠️ 使用感知专用轨（原片 {sense_info['original_size_mb']}MB → 转码 {sense_info['sense_size_mb']}MB）")
        print(f"     honesty_report.analysis_method 应记为 view_file_multimodal_sense_track")
        if sense_info.get("audio_path"):
            print(f"  紧急降级资产（_sense.mp4 仍传输失败时启用）：")
            print(f"     音轨 {sense_info['audio_path']} + 九宫格 {contact_sheet_path}")
            print(f"     降级感知 honesty_report.analysis_method 记为 audio_contact_sheet_degraded")
    print(f"  Grounding Payload: {payload_path}")
    print(f"  Whisper STT 作为 VO 转录的 Ground Truth（{len(stt)} 句）")
    print("=" * 60)


if __name__ == "__main__":
    main()
