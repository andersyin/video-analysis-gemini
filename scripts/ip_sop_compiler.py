#!/usr/bin/env python3
"""
Layer 4 资产编译器 — 将分析 JSON 转化为可执行的拍摄与声音 SOP

功能：
  1. 读取正式分析 JSON
  2. 编译《实拍与音频 SOP》（shooting_sop_<date>.md）
  3. 触发 synthesis_engine.py 公式提炼
  4. 触发音效库归档

产出:
  <archive-dir>/<account>/videos/<video-id>/shooting_sop_<date>.md

用法:
  python3 ip_sop_compiler.py \
    --archive-dir /path/to/archive \
    --account "kat-and-oliver" \
    --video-id "TOP01_xxxx" \
    --date 2026-07-25
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_helper import upsert_index  # noqa: E402


def load_analysis_json(archive_dir, account, video_id, date):
    """加载正式分析 JSON"""
    json_path = os.path.join(archive_dir, account, "videos", video_id, f"analysis_{date}.json")
    if not os.path.exists(json_path):
        print(f"分析文件不存在: {json_path}")
        return None, None
    with open(json_path) as f:
        return json.load(f), json_path


def load_qa_result(archive_dir, account, video_id):
    """加载质检结果"""
    qa_path = os.path.join(archive_dir, account, "videos", video_id, "_qa_result.json")
    if os.path.exists(qa_path):
        with open(qa_path) as f:
            return json.load(f)
    return None


def compile_shooting_sop(data, qa_result, account, video_id, date):
    """编译《实拍与音频 SOP》"""

    cine = data.get("cinematography", {})
    audio = data.get("audio", {})
    narr = data.get("narrative", {})
    sop = data.get("sop", {})
    ai_fx = data.get("ai_fx", {})

    shots = cine.get("shot_timeline", [])
    macro = cine.get("macro", {})
    vo = audio.get("voiceover_transcript", [])
    sfx_timeline = audio.get("sfx_timeline", [])
    bgm_timeline = audio.get("bgm_timeline", [])
    ducking = audio.get("ducking_and_silence", audio.get("silence_moments", []))
    # 软字段(top_soft)：AI 可能产出字符串/单对象，归一为字典列表，非结构化则置空
    if isinstance(ducking, dict):
        ducking = [ducking]
    elif not isinstance(ducking, list):
        ducking = []
    ducking = [d for d in ducking if isinstance(d, dict)]

    lines = []
    lines.append("# 实拍与音频 SOP")
    lines.append("")
    lines.append(f"> **账号**: {account}  ")
    lines.append(f"> **视频ID**: {video_id}  ")
    lines.append(f"> **日期**: {date}  ")
    lines.append(f"> **质检分数**: {qa_result.get('score', 'N/A') if qa_result else 'N/A'}/100  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Part 1: 实拍拍摄指导
    lines.append("## 一、实拍拍摄指导")
    lines.append("")
    lines.append("### 1.1 镜头机位与角度")
    lines.append("")
    lines.append("| # | 时间 | 镜头类型 | 机位高度 | 运镜 | 光圈 | 色温 | 备注 |")
    lines.append("|---|------|---------|---------|------|------|------|------|")
    for i, shot in enumerate(shots):
        start = shot.get("start_sec", 0)
        end = shot.get("end_sec", 0)
        shot_type = shot.get("shot_type", "")
        camera_height = shot.get("camera_height_cm", "")
        movement = shot.get("camera_movement", "")
        aperture = shot.get("dof", shot.get("aperture", ""))
        color_temp = shot.get("color_temp", shot.get("color_temp_k", ""))
        visual = str(shot.get("visual_content", ""))[:50]
        lines.append(f"| {i+1} | {start}-{end}s | {shot_type} | {camera_height}cm | {movement} | {aperture} | {color_temp} | {visual}... |")
    lines.append("")

    lines.append("### 1.2 镜头时长统计")
    lines.append("")
    total_shots = macro.get("total_shots", len(shots))
    asl = macro.get("avg_shot_length_sec", macro.get("asl_sec", 0))
    lines.append(f"- 总镜头数: {total_shots}")
    lines.append(f"- 平均镜长 (ASL): {asl}s")
    # 切频内联计算（analysis macro 无此字段，直接从时间轴推导）
    video_dur = shots[-1].get("end_sec", 0) if shots else 0
    if video_dur > 0 and total_shots > 0:
        cut_freq_min = round(total_shots / video_dur * 60, 1)
        cut_freq_sec = round(total_shots / video_dur, 2)
        lines.append(f"- 切频: {cut_freq_min} 次/分（{cut_freq_sec} 镜/秒）")
    else:
        lines.append("- 切频: N/A 次/分")
    lines.append("")

    shot_types = {}
    for s in shots:
        t = s.get("shot_type", "unknown")
        shot_types[t] = shot_types.get(t, 0) + 1
    if shot_types:
        lines.append("**镜头类型分布**：")
        for t, c in sorted(shot_types.items(), key=lambda x: -x[1]):
            lines.append(f"- {t}: {c} 次 ({c*100//len(shots)}%)")
        lines.append("")

    lines.append("### 1.3 可复用模块")
    lines.append("")
    # asset_reusability 可能是 dict（含 reusable_modules）或纯文本描述（2026-07-27 铁头阿彪01 字符串型崩溃修复）
    reusable = sop.get("asset_reusability", {})
    if isinstance(reusable, dict):
        modules = reusable.get("reusable_modules", [])
    else:
        lines.append(f"- {reusable}")
        lines.append("")
        modules = []
    if modules:
        lines.append("| # | 模块名 | 可复用 | 提示卡 |")
        lines.append("|---|--------|--------|--------|")
        for i, m in enumerate(modules):
            if isinstance(m, dict):
                name = m.get("name", "")
                reuse = m.get("reuse_observed", "")
                # prompt_card 缺失时兜底取模块描述，不留空列
                card = str(m.get("prompt_card") or m.get("description", ""))[:60]
            else:
                name = str(m)
                reuse = "有"
                card = str(m)[:60]
            lines.append(f"| {i+1} | {name} | {reuse} | {card} |")
        lines.append("")
    else:
        lines.append("_无可复用模块_")
        lines.append("")

    # Part 2: 音频与声音 SOP
    lines.append("## 二、音频与声音 SOP")
    lines.append("")

    lines.append("### 2.1 画外音 (VO) 台词本")
    lines.append("")
    if vo and isinstance(vo, list):
        lines.append("| # | 开始 | 结束 | 台词 |")
        lines.append("|---|------|------|------|")
        for i, v in enumerate(vo):
            lines.append(f"| {i+1} | {v.get('start_sec', 0)}s | {v.get('end_sec', 0)}s | {v.get('text', '')} |")
        lines.append("")
    else:
        lines.append("_无画外音_")
        lines.append("")

    lines.append("### 2.2 音效 (SFX) 库索引")
    lines.append("")
    if sfx_timeline:
        lines.append("| # | 时间 | SFX 名称 | 类型 | 分类 | 对齐画面 |")
        lines.append("|---|------|---------|------|------|---------|")
        for i, s in enumerate(sfx_timeline):
            name = s.get("type", s.get("sfx_name", ""))
            stype = s.get("type", "")
            category = s.get("category", "")
            sync = s.get("sync_with_visual", "")
            lines.append(f"| {i+1} | {s.get('second', 0)}s | {name} | {stype} | {category} | {sync} |")
        lines.append("")
    else:
        lines.append("_无 SFX_")
        lines.append("")

    lines.append("### 2.3 BGM 配乐与 Ducking 闪避")
    lines.append("")
    if bgm_timeline:
        lines.append("**BGM 变化时间轴**：")
        lines.append("")
        lines.append("| # | 时间 | 变化类型 | 风格 | 描述 |")
        lines.append("|---|------|---------|------|------|")
        for i, b in enumerate(bgm_timeline):
            sec = b.get("second", 0)
            change_type = b.get("change_type", b.get("event", ""))
            genre = b.get("genre", "")
            desc = b.get("description", "")
            lines.append(f"| {i+1} | {sec}s | {change_type} | {genre} | {desc} |")
        lines.append("")
    else:
        lines.append("_无 BGM 变化记录_")
        lines.append("")

    if ducking:
        lines.append("**Ducking 与静音事件**：")
        lines.append("")
        lines.append("| # | 时间 | 效果 | 衰减 dB | 持续s | 触发事件 |")
        lines.append("|---|------|------|---------|-------|---------|")
        for i, d in enumerate(ducking):
            sec = d.get("second", 0)
            effect = d.get("effect", d.get("type", ""))
            reduction = d.get("ducking_attenuation_db", d.get("reduction_db", ""))
            duration = d.get("duration_sec", d.get("duration_ms", ""))
            trigger = d.get("trigger_event", d.get("trigger_source", "SFX/VO"))
            lines.append(f"| {i+1} | {sec}s | {effect} | {reduction} | {duration} | {trigger} |")
        lines.append("")
        lines.append("**Ducking 闪避参数指导**：")
        lines.append("- 衰减幅度: 建议使用上方 dB 值（精确到 1dB）")
        lines.append("- 闪避触发: SFX 出现时立即触发，持续到 SFX 结束")
        lines.append("- 恢复曲线: 建议使用指数恢复曲线（100ms 内恢复）")
        lines.append("")
    else:
        lines.append("_无 Ducking 事件_")
        lines.append("")

    # Part 3: AI 后期合成指导
    lines.append("## 三、AI 后期合成指导")
    lines.append("")
    ai_modules = ai_fx.get("scene_timeline", ai_fx.get("ai_modules", []))
    if ai_modules:
        lines.append("| # | 时间 | 技术 | 工具 | 混合方式 |")
        lines.append("|---|------|------|------|---------|")
        for i, m in enumerate(ai_modules):
            start = m.get("start_sec", "")
            end = m.get("end_sec", "")
            tech = m.get("technique", m.get("name", ""))
            tool = m.get("tool_guess", m.get("software", ""))
            blend = m.get("blend_method", m.get("params", ""))
            lines.append(f"| {i+1} | {start}-{end}s | {tech} | {tool} | {blend} |")
        lines.append("")
    else:
        lines.append("_无 AI 后期合成_")
        lines.append("")

    # Part 4: 叙事结构参考
    lines.append("## 四、叙事结构参考")
    lines.append("")
    narr_macro = narr.get("macro", {})
    attention = narr_macro.get("attention_curve", {})
    if isinstance(attention, dict):
        lines.append(f"- 开场钩子: {attention.get('hook_sec', 'N/A')}")
        lines.append(f"- 高潮点: {attention.get('climax_sec', 'N/A')}")
        lines.append(f"- 反转点: {attention.get('reversal_sec', 'N/A')}")
    else:
        lines.append(f"- 注意力曲线: {attention}")
    lines.append(f"- 叙事模板: {narr_macro.get('narrative_template', 'N/A')}")
    lines.append(f"- 完整脚本: {str(narr.get('script_full_text', 'N/A'))[:200]}...")
    lines.append("")
    lines.append("**情绪曲线**：")
    lines.append("")
    emotions = narr.get("emotional_timeline", [])
    if emotions:
        lines.append("| # | 开始 | 结束 | 情绪 | 强度 |")
        lines.append("|---|------|------|------|------|")
        for i, e in enumerate(emotions):
            lines.append(f"| {i+1} | {e.get('start_sec', 0)}s | {e.get('end_sec', 0)}s | {e.get('emotion', '')} | {e.get('intensity_1to10', e.get('intensity', ''))} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*由 `ip_sop_compiler.py` 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Layer 4 资产编译器")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", required=True, help="账号名")
    parser.add_argument("--video-id", required=True, help="视频ID")
    parser.add_argument("--date", required=True, help="分析日期 YYYY-MM-DD")
    args = parser.parse_args()

    print("=" * 60)
    print("Layer 4 资产编译")
    print(f"视频: {args.video_id}")
    print("=" * 60)

    data, json_path = load_analysis_json(args.archive_dir, args.account, args.video_id, args.date)
    if not data:
        sys.exit(1)

    qa_result = load_qa_result(args.archive_dir, args.account, args.video_id)

    # Layer 4 入口门禁：必须有 qa_result 且 qa_passed=True
    if not qa_result:
        print("GATE FAIL: _qa_result.json 不存在")
        print("  Layer 4 入口检查失败 — 必须先完成 Layer 3 Pro 质检")
        print("  执行: python3 pro_qa_inspector.py --archive-dir ... --account ... --video-id ... --date ...")
        sys.exit(1)

    if not qa_result.get("qa_passed", False):
        print(f"GATE FAIL: 质检未通过 (Score: {qa_result.get('score', 'N/A')})")
        print("  Layer 4 入口检查失败 — Pro 质检 Score >= 90 才能编译 SOP")
        print("  请先修复 Layer 3 探针问题，重新质检")
        sys.exit(1)

    print(f"GATE OK: 质检通过 (Score: {qa_result.get('score', 'N/A')})")

    print("\n编译《实拍与音频 SOP》...")
    sop_md = compile_shooting_sop(data, qa_result, args.account, args.video_id, args.date)

    video_dir = os.path.join(args.archive_dir, args.account, "videos", args.video_id)
    sop_path = os.path.join(video_dir, f"shooting_sop_{args.date}.md")
    with open(sop_path, "w", encoding="utf-8") as f:
        f.write(sop_md)
    print(f"SOP 已保存: {sop_path}")

    # 触发 synthesis_engine.py
    synth_path = os.path.join(os.path.dirname(__file__), "synthesis_engine.py")
    if os.path.exists(synth_path):
        print("\n触发 synthesis_engine.py 公式提炼...")
        import subprocess
        cmd = ["python3", synth_path, "--archive-dir", args.archive_dir, "--account", args.account]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                print("公式提炼完成")
            else:
                print(f"公式提炼失败: {result.stderr[:200]}")
        except Exception as e:
            print(f"synthesis_engine.py 执行失败: {e}")
    else:
        print("synthesis_engine.py 不存在，跳过公式提炼")

    # 触发音效库归档
    archiver_path = os.path.join(os.path.dirname(__file__), "asset_pool_archiver.py")
    if os.path.exists(archiver_path):
        print("\n触发 asset_pool_archiver.py 音效库归档...")
        import subprocess
        cmd = ["python3", archiver_path, "--archive-dir", args.archive_dir,
               "--account", args.account, "--video-id", args.video_id, "--date", args.date]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                print("音效库归档完成")
            else:
                print(f"音效库归档失败: {result.stderr[:200]}")
        except Exception as e:
            print(f"asset_pool_archiver.py 执行失败: {e}")
    else:
        print("asset_pool_archiver.py 不存在，跳过音效库归档")

    # 更新状态机（幂等：已交付仅刷新 sop_path，不重复追加 history）
    state_path = os.path.join(video_dir, "_state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
    if state.get("current_state") != "PASS_DELIVERED":
        newly_delivered = True
        state["current_state"] = "PASS_DELIVERED"
        state.setdefault("history", []).append({
            "state": "PASS_DELIVERED",
            "timestamp": datetime.now().isoformat(),
            "sop_path": sop_path,
        })
    else:
        newly_delivered = False
    state["sop_path"] = sop_path
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("状态更新: -> PASS_DELIVERED")

    # P1-3 用后即焚（SentientOS ProactiveCycle 链尾 wipe 借鉴，2026-07-28）：
    # 仅在【首次转入 PASS_DELIVERED】=整条 L2→L4 链成功后，隔离清理当前单视频过程文件。
    # opt-in（SENTIENT_CLEANUP_ON_DELIVER=1 才触发）=默认零行为变更；隔离非删除=可逆；
    # 失败仅告警不回滚交付（PASS_DELIVERED 已落盘）。待下次真实 overnight run 打开验证后转默认开启。
    if newly_delivered and os.environ.get("SENTIENT_CLEANUP_ON_DELIVER") == "1":
        import subprocess
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_helper.py")
        qdir = os.path.join(args.archive_dir, "_process_archive")
        try:
            r = subprocess.run(
                ["python3", helper, "--cleanup-sense", "--account", args.account,
                 "--video-id", args.video_id, "--archive-dir", args.archive_dir,
                 "--quarantine-dir", qdir, "--apply"],
                capture_output=True, text=True, timeout=60)
            print(f"🧹 链尾即焚（隔离至 _process_archive）：rc={r.returncode}"
                  + (f" | {r.stderr.strip().splitlines()[-1]}" if r.stderr.strip() else ""))
        except Exception as e:
            print(f"⚠️ 链尾即焚失败（不影响交付，已 PASS_DELIVERED）：{e}")

    # 回写全局账号索引（下次 Layer 1 baseline 注入即为真实数据）
    try:
        shots = data.get("cinematography", {}).get("shot_timeline", [])
        asl = data.get("cinematography", {}).get("macro", {}).get("avg_shot_length_sec")
        analyzed = 0
        videos_root = Path(args.archive_dir) / args.account / "videos"
        if videos_root.is_dir():
            analyzed = sum(1 for d in videos_root.iterdir()
                           if d.is_dir() and list(d.glob("analysis_*.json")))
        upsert_index(args.archive_dir, args.account,
                     analyzed_count=analyzed,
                     asl_mean=asl)
        print("全局索引 _index.json 已回写（analyzed_count/asl_mean）")
    except Exception as e:
        print(f"⚠️ _index.json 回写失败（不阻断交付）: {e}")

    print(f"\n{'='*60}")
    print(f"Layer 4 完成")
    print(f"  分析 JSON: {json_path}")
    print(f"  SOP: {sop_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
