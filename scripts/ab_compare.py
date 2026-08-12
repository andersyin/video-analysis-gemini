#!/usr/bin/env python3
"""A/B 对比回归工具 — skill 流水线 vs 直接对话 prompt（正式版）

用途：每次 skill 改版后，对固定测试视频集跑 A/B 对比，防止质量回归。

修复历史（2026-07-26）：
  旧版 experiments/ab_test/ab_compare.py 的胜负判定为 `"A" if a>b else "B"`，
  等值时默认判 B，单次测试产生 5 项误判（故事节拍/null 比例/重复率/JSON 体积）。
  本版统一走 _winner() 三路判定（A/B/tie）。

用法:
  python3 ab_compare.py \
    --a /path/to/analysis_skill.json \
    --b /path/to/analysis_direct.json \
    --duration 117.84

  # 输出 JSON（供回归脚本消费）
  python3 ab_compare.py --a ... --b ... --duration ... --json-out result.json
"""
import argparse
import json
import sys
from pathlib import Path


def extract_metrics(data, duration_sec):
    """从分析 JSON 提取对比指标"""
    cine = data.get("cinematography", {})
    audio = data.get("audio", {})
    narr = data.get("narrative", {})
    ai_fx = data.get("ai_fx", {})
    meta = data.get("_meta", {})

    shots = cine.get("shot_timeline", [])
    sfx = audio.get("sfx_timeline", [])
    vo = audio.get("voiceover_transcript", [])
    bgm = audio.get("bgm_timeline", [])
    duck_raw = audio.get("ducking_and_silence", [])
    # ducking_and_silence 可能是 list（事件列表）或 string（文字描述）
    duck = duck_raw if isinstance(duck_raw, list) else []
    beats = narr.get("story_beats", [])
    quotes = narr.get("all_quotes", [])
    emo_cine = cine.get("macro", {}).get("visual_emotion_curve", [])
    if isinstance(emo_cine, str):
        emo_cine = []
    micro_motions = ai_fx.get("micro_motion_moments", [])
    scene_tl = ai_fx.get("scene_timeline", [])

    # 覆盖率检查
    last_end = 0
    for s in shots:
        e = s.get("end_sec", 0)
        if isinstance(e, (int, float)) and e > last_end:
            last_end = e
    coverage_gap = abs(last_end - duration_sec) if duration_sec else 0

    # 幻觉检测：时间轴超出真实时长 5% 以上
    hallucination_overshoot_sec = max(0, last_end - duration_sec) if duration_sec else 0
    hallucination_flag = hallucination_overshoot_sec > duration_sec * 0.05 if duration_sec else False

    # macro 一致性
    total_shots_macro = cine.get("macro", {}).get("total_shots", 0)
    asl_macro = cine.get("macro", {}).get("avg_shot_length_sec", 0)
    asl_calc = 0
    if shots:
        durations = [s.get("end_sec", 0) - s.get("start_sec", 0) for s in shots]
        asl_calc = sum(durations) / len(durations) if durations else 0

    # VO ratio
    vo_ratio_macro = audio.get("macro", {}).get("voiceover_ratio_pct", 0)
    vo_ratio_calc = 0
    if duration_sec and vo:
        vo_total = 0
        for v in vo:
            s = v.get("start_sec", 0)
            e = v.get("end_sec", 0)
            if isinstance(s, (int, float)) and isinstance(e, (int, float)):
                vo_total += max(0, e - s)
        vo_ratio_calc = round(vo_total / duration_sec * 100, 1) if duration_sec else 0

    # 诚实度报告
    hr = meta.get("honesty_report", {})
    has_honesty = bool(hr)
    hr_details = 0
    if has_honesty:
        for sec_data in hr.get("sections", {}).values():
            if isinstance(sec_data, dict):
                hr_details += len(sec_data.get("specific_details_only_from_watching", []))

    # null 字段统计（诚实标注不确定）
    null_count = 0
    field_count = 0

    def count_nulls(obj, depth=0):
        nonlocal null_count, field_count
        if depth > 5:
            return
        if isinstance(obj, dict):
            for v in obj.values():
                if v is None:
                    null_count += 1
                    field_count += 1
                elif isinstance(v, (dict, list)):
                    count_nulls(v, depth + 1)
                else:
                    field_count += 1
        elif isinstance(obj, list):
            for item in obj:
                count_nulls(item, depth + 1)

    count_nulls(data)

    # 模板文本检测：跨条目描述重复率
    def detect_template_ratio(items, field):
        texts = [str(item.get(field, "")) for item in items if isinstance(item, dict)]
        texts = [t for t in texts if t]
        if len(texts) < 2:
            return 0
        unique = len(set(texts))
        return round((1 - unique / len(texts)) * 100, 1)

    sfx_template_ratio = detect_template_ratio(sfx, "description")
    shot_template_ratio = detect_template_ratio(shots, "visual_content")

    # JSON 体积
    json_size = len(json.dumps(data, ensure_ascii=False))

    return {
        "shots": len(shots),
        "shot_density_per_10s": round(len(shots) / duration_sec * 10, 1) if duration_sec else 0,
        "coverage_gap_sec": round(coverage_gap, 2),
        "coverage_pct": round((1 - coverage_gap / duration_sec) * 100, 1) if duration_sec else 0,
        "hallucination_overshoot_sec": round(hallucination_overshoot_sec, 2),
        "hallucination_flag": hallucination_flag,
        "sfx": len(sfx),
        "sfx_density_per_10s": round(len(sfx) / duration_sec * 10, 1) if duration_sec else 0,
        "vo_segments": len(vo),
        "vo_density_per_10s": round(len(vo) / duration_sec * 10, 1) if duration_sec else 0,
        "bgm_changes": len(bgm),
        "ducking_events": len(duck),
        "story_beats": len(beats),
        "quotes": len(quotes),
        "emotion_segments": len(emo_cine) if isinstance(emo_cine, list) else 0,
        "micro_motions": len(micro_motions),
        "scene_timeline": len(scene_tl),
        "macro_total_shots": total_shots_macro,
        "macro_shots_match": total_shots_macro == len(shots),
        "asl_macro": asl_macro,
        "asl_calc": round(asl_calc, 2),
        "asl_match": abs(asl_macro - asl_calc) < 0.5 if asl_macro and asl_calc else None,
        "vo_ratio_macro": vo_ratio_macro,
        "vo_ratio_calc": vo_ratio_calc,
        "vo_ratio_match": abs(vo_ratio_macro - vo_ratio_calc) < 15 if vo_ratio_macro and vo_ratio_calc else None,
        "has_honesty_report": has_honesty,
        "honesty_details_count": hr_details,
        "null_fields": null_count,
        "total_fields": field_count,
        "null_ratio_pct": round(null_count / max(field_count, 1) * 100, 1),
        "sfx_template_ratio_pct": sfx_template_ratio,
        "shot_template_ratio_pct": shot_template_ratio,
        "script_full_text_len": len(narr.get("script_full_text", "")),
        "json_size_kb": round(json_size / 1024, 1),
    }


def _winner(a_val, b_val, higher_better=True):
    """三路胜负判定：等值必须判 tie（2026-07-26 修复，旧版等值默认判 B）"""
    if a_val == b_val:
        return "tie"
    if higher_better:
        return "A" if a_val > b_val else "B"
    return "A" if a_val < b_val else "B"


def _winner_bool(a_ok, b_ok):
    """布尔指标三路判定"""
    if a_ok == b_ok:
        return "tie"
    return "A" if a_ok else "B"


def compare(a_metrics, b_metrics, duration_sec):
    """生成对比报告"""
    rows = []

    def row(label, a_val, b_val, winner=None, note=""):
        rows.append({
            "metric": label,
            "path_a_skill": a_val,
            "path_b_direct": b_val,
            "winner": winner or "—",
            "note": note,
        })

    # 覆盖与密度
    row("镜头数", a_metrics["shots"], b_metrics["shots"],
        _winner(a_metrics["shots"], b_metrics["shots"]), "更多=更细致")
    row("镜头密度/10s", a_metrics["shot_density_per_10s"], b_metrics["shot_density_per_10s"],
        _winner(a_metrics["shot_density_per_10s"], b_metrics["shot_density_per_10s"]),
        "下限分档: ≥3.3/10s(0-60s) ≥1.5/10s(60-300s)")
    row("时间轴覆盖率%", a_metrics["coverage_pct"], b_metrics["coverage_pct"],
        _winner(a_metrics["coverage_pct"], b_metrics["coverage_pct"]),
        "最后镜end_sec ≈ 视频时长")
    row("覆盖偏差(s)", a_metrics["coverage_gap_sec"], b_metrics["coverage_gap_sec"],
        _winner(a_metrics["coverage_gap_sec"], b_metrics["coverage_gap_sec"], higher_better=False),
        "越小越好")

    row("SFX数", a_metrics["sfx"], b_metrics["sfx"],
        _winner(a_metrics["sfx"], b_metrics["sfx"]),
        "下限分档: ≥2/10s(0-60s) ≥1/10s(60-300s)")
    row("SFX密度/10s", a_metrics["sfx_density_per_10s"], b_metrics["sfx_density_per_10s"],
        _winner(a_metrics["sfx_density_per_10s"], b_metrics["sfx_density_per_10s"]))

    row("VO段数", a_metrics["vo_segments"], b_metrics["vo_segments"],
        _winner(a_metrics["vo_segments"], b_metrics["vo_segments"]),
        "最低要求: ≥1/10s")
    row("VO密度/10s", a_metrics["vo_density_per_10s"], b_metrics["vo_density_per_10s"],
        _winner(a_metrics["vo_density_per_10s"], b_metrics["vo_density_per_10s"]))

    row("BGM变化", a_metrics["bgm_changes"], b_metrics["bgm_changes"],
        _winner(a_metrics["bgm_changes"], b_metrics["bgm_changes"]))
    row("Ducking事件", a_metrics["ducking_events"], b_metrics["ducking_events"],
        _winner(a_metrics["ducking_events"], b_metrics["ducking_events"]),
        "ducking字段为文字描述非列表→计为0事件")

    # 幻觉检测
    row("时间轴幻觉超出(s)", a_metrics["hallucination_overshoot_sec"], b_metrics["hallucination_overshoot_sec"],
        _winner(a_metrics["hallucination_overshoot_sec"], b_metrics["hallucination_overshoot_sec"], higher_better=False),
        ">5%时长=幻觉，越小越好(0=无幻觉)")
    row("时间轴幻觉", "❌无" if not a_metrics["hallucination_flag"] else "⚠️有", "❌无" if not b_metrics["hallucination_flag"] else "⚠️有",
        _winner_bool(not a_metrics["hallucination_flag"], not b_metrics["hallucination_flag"]),
        "时间轴超出真实时长5%以上=幻觉")

    row("故事节拍", a_metrics["story_beats"], b_metrics["story_beats"],
        _winner(a_metrics["story_beats"], b_metrics["story_beats"]))
    row("情绪段数", a_metrics["emotion_segments"], b_metrics["emotion_segments"],
        _winner(a_metrics["emotion_segments"], b_metrics["emotion_segments"]))
    row("金句数", a_metrics["quotes"], b_metrics["quotes"],
        _winner(a_metrics["quotes"], b_metrics["quotes"]))

    row("微动作捕捉", a_metrics["micro_motions"], b_metrics["micro_motions"],
        _winner(a_metrics["micro_motions"], b_metrics["micro_motions"]),
        "Gemini独有能力，skill强制要求")

    # 一致性
    row("macro.total_shots匹配", "✅" if a_metrics["macro_shots_match"] else "❌",
        "✅" if b_metrics["macro_shots_match"] else "❌",
        _winner_bool(a_metrics["macro_shots_match"], b_metrics["macro_shots_match"]),
        "声明总数 = 实际条数")
    row("ASL一致性", "✅" if a_metrics["asl_match"] else "❌",
        "✅" if b_metrics["asl_match"] else "❌",
        _winner_bool(a_metrics["asl_match"], b_metrics["asl_match"]),
        "声明ASL = 计算ASL(±0.5s)")
    row("VO ratio一致性", "✅" if a_metrics["vo_ratio_match"] else "❌",
        "✅" if b_metrics["vo_ratio_match"] else "❌",
        _winner_bool(a_metrics["vo_ratio_match"], b_metrics["vo_ratio_match"]),
        "声明ratio = 计算ratio(±15%)")

    # 诚实度
    row("有honesty_report", "✅" if a_metrics["has_honesty_report"] else "❌",
        "✅" if b_metrics["has_honesty_report"] else "❌",
        _winner_bool(a_metrics["has_honesty_report"], b_metrics["has_honesty_report"]),
        "skill强制要求")
    row("honesty细节条数", a_metrics["honesty_details_count"], b_metrics["honesty_details_count"],
        _winner(a_metrics["honesty_details_count"], b_metrics["honesty_details_count"]))
    row("null字段比例%", a_metrics["null_ratio_pct"], b_metrics["null_ratio_pct"],
        _winner(a_metrics["null_ratio_pct"], b_metrics["null_ratio_pct"]),
        "越高=越诚实标注不确定（但太多=信息缺失）")

    # 模板化检测
    row("SFX描述重复率%", a_metrics["sfx_template_ratio_pct"], b_metrics["sfx_template_ratio_pct"],
        _winner(a_metrics["sfx_template_ratio_pct"], b_metrics["sfx_template_ratio_pct"], higher_better=False),
        "越低越好（0%=无模板）")
    row("镜头描述重复率%", a_metrics["shot_template_ratio_pct"], b_metrics["shot_template_ratio_pct"],
        _winner(a_metrics["shot_template_ratio_pct"], b_metrics["shot_template_ratio_pct"], higher_better=False),
        "越低越好")

    # 体积
    row("JSON体积(KB)", a_metrics["json_size_kb"], b_metrics["json_size_kb"],
        _winner(a_metrics["json_size_kb"], b_metrics["json_size_kb"]),
        "更大=更多字段填充")
    row("script全文长度", a_metrics["script_full_text_len"], b_metrics["script_full_text_len"],
        _winner(a_metrics["script_full_text_len"], b_metrics["script_full_text_len"]))

    return rows


def main():
    parser = argparse.ArgumentParser(description="A/B 对比回归工具: skill流水线 vs 直接对话prompt")
    parser.add_argument("--a", required=True, help="Path A (skill) JSON 路径")
    parser.add_argument("--b", required=True, help="Path B (direct) JSON 路径")
    parser.add_argument("--duration", type=float, required=True, help="视频时长(秒)")
    parser.add_argument("--json-out", default="", help="结果 JSON 输出路径（供回归消费，可选）")
    args = parser.parse_args()

    with open(args.a) as f:
        data_a = json.load(f)
    with open(args.b) as f:
        data_b = json.load(f)

    metrics_a = extract_metrics(data_a, args.duration)
    metrics_b = extract_metrics(data_b, args.duration)
    rows = compare(metrics_a, metrics_b, args.duration)

    # 胜负统计
    a_wins = sum(1 for r in rows if r["winner"] == "A")
    b_wins = sum(1 for r in rows if r["winner"] == "B")
    ties = sum(1 for r in rows if r["winner"] in ("tie", "—"))

    print("=" * 80)
    print("A/B 对比报告: skill流水线 (A) vs 直接对话prompt (B)")
    print(f"视频时长: {args.duration}s")
    print("=" * 80)

    print(f"\n{'指标':<25} {'A (skill)':<20} {'B (direct)':<20} {'胜者':<8} {'备注'}")
    print("-" * 80)
    for r in rows:
        print(f"{r['metric']:<25} {str(r['path_a_skill']):<20} {str(r['path_b_direct']):<20} {r['winner']:<8} {r['note']}")

    print("-" * 80)
    print(f"\n胜负统计: A (skill) 胜 {a_wins} | B (direct) 胜 {b_wins} | 平局 {ties}")

    result = {
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "comparison_rows": rows,
        "summary": {"a_wins": a_wins, "b_wins": b_wins, "ties": ties},
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n结果已写入: {args.json_out}")
    else:
        print(f"\n完整 metrics JSON:\n{json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
