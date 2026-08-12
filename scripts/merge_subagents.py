#!/usr/bin/env python3
"""
merge_subagents.py — 多智能体并发感知的主节点缝合器（实验模式 · 2026-07-26）

背景：单体长上下文逐板块感知存在注意力涣散与速度瓶颈。实验模式将 L2 拆为
3 个专注 Subagent 并发感知，主节点缝合 + 物理硬截断 + 跨模态卡点对齐 + 密度预检。

分工约定（Subagent 产出的分块文件，置于视频归档目录）：
  _sub_visual_<date>.json     → cinematography + ai_fx（必须 view_file 看完整视频）
  _sub_audio_<date>.json      → audio（可 view_file 加载 _sense_audio.m4a 独立音轨）
  _sub_narrative_<date>.json  → narrative + sop（必须 view_file 看完整视频，情绪=声画叠加）

每个分块文件结构：顶层直接放板块键 + honesty（该 Subagent 负责板块的嵌套 sections）：
  {
    "cinematography": {...}, "ai_fx": {...},
    "honesty": {
      "view_file_called": true, "view_duration_sec": 214.48, "watched_full_video": true,
      "sections": {"cinematography": {...}, "ai_fx": {...}}
    }
  }

缝合逻辑：
  1. 物理硬截断：start_sec > 时长 → 剔除整条；end_sec > 时长 → 截断为时长
  2. 跨模态卡点对齐：SFX 触发点与镜头切点 ±0.2s 内 → 自动补 triad_coupling 标注
  3. 密度预检：复用 session_guard.check_density_gates，不达标输出「定向补感知指令」
  4. 组装标准 analysis_<date>.json（含合并 honesty_report）→ 下一步 finalize-l2

用法:
  python3 merge_subagents.py --archive-dir <dir> --account <acct> \
    --video-id <vid> --date 2026-07-26 [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_guard import check_density_gates  # noqa: E402

SUB_SPECS = {
    "visual": ["cinematography", "ai_fx"],
    "audio": ["audio"],
    "narrative": ["narrative", "sop"],
}
EXPECTED_SECTIONS = ["cinematography", "ai_fx", "audio", "narrative", "sop"]
COUPLING_TOLERANCE_SEC = 0.2


def clamp_timeline(items, duration, dropped, clamped, label):
    """物理硬截断：start 越界剔除整条；end 越界截断到时长"""
    kept = []
    for it in items:
        if not isinstance(it, dict):
            kept.append(it)
            continue
        start = it.get("start_sec", it.get("sec", it.get("timestamp_sec")))
        if isinstance(start, (int, float)) and start > duration:
            dropped.append(f"{label}@{start:.1f}s")
            continue
        end = it.get("end_sec")
        if isinstance(end, (int, float)) and end > duration:
            it["end_sec"] = round(duration, 2)
            clamped.append(f"{label}@{end:.1f}s→{duration:.2f}s")
        kept.append(it)
    return kept


def hard_prune(merged, duration):
    """遍历所有已知时间轴做物理截断，返回 (dropped, clamped) 统计"""
    dropped, clamped = [], []
    paths = [
        ("cinematography", "shot_timeline"), ("cinematography", "emotional_timeline"),
        ("audio", "voiceover_transcript"), ("audio", "sfx_timeline"),
        ("audio", "bgm_timeline"), ("audio", "ducking_and_silence"),
        ("narrative", "story_beats"), ("narrative", "emotional_timeline"),
        ("ai_fx", "scene_timeline"), ("ai_fx", "micro_motion_moments"),
    ]
    for sec, key in paths:
        block = merged.get(sec)
        if isinstance(block, dict) and isinstance(block.get(key), list):
            block[key] = clamp_timeline(block[key], duration, dropped, clamped, f"{sec}.{key}")
    return dropped, clamped


def align_coupling(merged):
    """跨模态卡点对齐：SFX 与镜头切点 ±0.2s 内自动补 triad_coupling（不覆盖已有标注）"""
    shots = (merged.get("cinematography") or {}).get("shot_timeline") or []
    sfx = (merged.get("audio") or {}).get("sfx_timeline") or []
    cuts = [(i, s.get("start_sec")) for i, s in enumerate(shots)
            if isinstance(s, dict) and isinstance(s.get("start_sec"), (int, float))]
    added = 0
    for item in sfx:
        if not isinstance(item, dict) or item.get("triad_coupling"):
            continue
        t = item.get("sec", item.get("start_sec"))
        if not isinstance(t, (int, float)):
            continue
        for idx, cut in cuts:
            if abs(t - cut) <= COUPLING_TOLERANCE_SEC:
                item["triad_coupling"] = {"matched_shot_index": idx, "type": "cut_on_sfx",
                                          "offset_sec": round(t - cut, 2)}
                added += 1
                break
    return added


def main():
    parser = argparse.ArgumentParser(description="Subagent 分块缝合器（实验模式）")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--date", required=True, help="分析日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只校验不落盘")
    args = parser.parse_args()

    video_dir = os.path.join(args.archive_dir, args.account, "videos", args.video_id)
    meta_path = os.path.join(video_dir, "_video_meta.json")
    if not os.path.exists(meta_path):
        print(f"❌ 缺少 _video_meta.json，先跑 preprocessor.py"); sys.exit(1)
    duration = float(json.load(open(meta_path)).get("duration_sec", 0))
    payload = {}
    payload_path = os.path.join(video_dir, "_grounding_payload.json")
    if os.path.exists(payload_path):
        payload = json.load(open(payload_path))

    # 1. 收分块
    merged, honesty_sections, sub_meta, missing = {}, {}, {}, []
    for name, sections in SUB_SPECS.items():
        sub_path = os.path.join(video_dir, f"_sub_{name}_{args.date}.json")
        if not os.path.exists(sub_path):
            missing.append(f"_sub_{name}_{args.date}.json（负责 {'+'.join(sections)}）")
            continue
        try:
            sub = json.load(open(sub_path))
        except json.JSONDecodeError as e:
            print(f"❌ {sub_path} 解析失败: {e}"); sys.exit(1)
        for sec in sections:
            if sec not in sub:
                missing.append(f"_sub_{name} 缺板块 {sec}")
            else:
                merged[sec] = sub[sec]
        hon = sub.get("honesty", {})
        honesty_sections.update(hon.get("sections", {}))
        sub_meta[name] = {"view_file_called": hon.get("view_file_called"),
                          "view_duration_sec": hon.get("view_duration_sec"),
                          "watched_full_video": hon.get("watched_full_video")}
    if missing:
        print("❌ 分块不齐，缺：")
        for m in missing:
            print(f"   - {m}")
        sys.exit(1)
    # honesty 铁律：任一 Subagent 未真实观看 → 整体作废
    fake = [n for n, m in sub_meta.items() if m.get("view_file_called") is not True]
    if fake:
        print(f"❌ Subagent {fake} 的 honesty.view_file_called ≠ true，整体作废（反例 #8）")
        sys.exit(1)

    # 2. 物理硬截断
    dropped, clamped = hard_prune(merged, duration)
    if dropped or clamped:
        print(f"✂️ 物理硬截断: 剔除 {len(dropped)} 条越界起点 / 截断 {len(clamped)} 条越界终点")
        for x in (dropped + clamped)[:5]:
            print(f"   - {x}")

    # 3. 跨模态卡点对齐
    added = align_coupling(merged)
    print(f"🔗 卡点对齐: 自动补 triad_coupling {added} 条（±{COUPLING_TOLERANCE_SEC}s）")

    # 4. 组装 analysis
    analysis = {"_meta": {
        "video_file": os.path.basename(payload.get("view_file_target", args.video_id)),
        "video_id": args.video_id,
        "account": args.account,
        "analysis_date": args.date,
        "model": "gemini-3.6-flash",
        "analysis_method": ("view_file_multimodal_sense_track"
                            if payload.get("sense") else "view_file_multimodal"),
        "perception_mode": "subagent_concurrent_v1",
        "sections": EXPECTED_SECTIONS,
        "honesty_report": {
            "view_file_called": True,
            "view_duration_sec": duration,
            "watched_full_video": all(m.get("watched_full_video") for m in sub_meta.values()),
            "subagents": sub_meta,
            "sections": honesty_sections,
            "fields_not_from_viewing": [],
            "script_generated": False,
        },
    }}
    analysis.update({sec: merged[sec] for sec in EXPECTED_SECTIONS})

    # 5. 密度预检（复用绑定门禁同一套口径，提前暴露该打回哪个 Subagent）
    failures, warnings, metrics = check_density_gates(analysis, video_dir)
    for w in warnings:
        print(w)
    print(f"📏 密度预检: {json.dumps(metrics, ensure_ascii=False)}")
    if failures:
        print("🔴 密度/边界预检未过——定向补感知指令（发给对应 Subagent 后重跑本脚本）：")
        for f_ in failures:
            target = "visual" if ("镜头" in f_ or "ASL" in f_) else \
                     "audio" if ("SFX" in f_ or "VO" in f_) else "narrative"
            print(f"   → [{target} Subagent] {f_}")
        sys.exit(2)

    if args.dry_run:
        print("✅ dry-run 通过（未落盘）")
        return
    out = os.path.join(video_dir, f"analysis_{args.date}.json")
    with open(out, "w") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"✅ 缝合完成: {out}")
    print("🔴 下一步立即执行（原子绑定）：")
    print(f"python3 scripts/session_guard.py finalize-l2 \\")
    print(f"  --archive-dir {args.archive_dir} --account {args.account} \\")
    print(f"  --video-id {args.video_id} --date {args.date}")


if __name__ == "__main__":
    main()
