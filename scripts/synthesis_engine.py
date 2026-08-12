#!/usr/bin/env python3
"""账号级报告自动汇聚引擎 —— 从底层 JSON 自动计算参数矩阵并生成 Markdown 报告。

用法:
  python synthesis_engine.py --archive-dir /path/to/archive --account "AccountD"
  python synthesis_engine.py --archive-dir /path/to/archive --account "AccountD" --date 2026-07-24

产出:
  <archive-dir>/<account>/account_formula_<date>.md  — 账号级公式提炼报告
"""
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_helper import upsert_index  # noqa: E402


def load_account(archive_dir, account, date_filter=None):
    """加载账号下所有分析 JSON。"""
    videos_dir = Path(archive_dir) / account / "videos"
    if not videos_dir.exists():
        return [], None

    files = sorted(videos_dir.glob("*/analysis_*.json"))
    if date_filter:
        files = [f for f in files if f.name == f"analysis_{date_filter}.json"]

    results = []
    for f in files:
        try:
            data = json.loads(f.read_text("utf-8"))
            results.append((f.parent.name, data))
        except Exception:
            pass

    return results, videos_dir


def extract_metrics(all_data):
    """从所有视频 JSON 中提取关键指标。"""
    metrics = {
        "video_count": len(all_data),
        "total_duration_sec": 0,
        "avg_duration_sec": 0,
        # Cinematography
        "total_shots": [],
        "avg_shot_lengths": [],
        "asls": [],  # Average Shot Length per video
        "cut_freqs": [],  # shots per second
        "camera_heights": [],
        "shot_types": Counter(),
        "camera_movements": Counter(),
        "compositions": Counter(),
        "lightings": Counter(),
        "color_temps": [],
        "transitions": Counter(),
        # Audio
        "vo_counts": [],
        "sfx_counts": [],
        "bgm_counts": [],
        "silence_counts": [],
        "vo_ratios": [],
        "sfx_density": [],  # SFX per 10s
        "bgm_genres": Counter(),
        "speakers": Counter(),
        "tones": Counter(),
        # Narrative
        "emo_segments": [],
        "story_beats": Counter(),
        "hook_types": Counter(),
        "quote_count": 0,
        "pun_count": 0,
        "narrative_templates": Counter(),
        # AI/FX
        "techniques": Counter(),
        "tool_guesses": Counter(),
        "micro_motion_ratios": [],
        # SOP
        "complexity_ratings": Counter(),
        "software_chains": Counter(),
        "brand_count": 0,
    }

    for vid, data in all_data:
        # Duration
        cine = data.get("cinematography", {})
        macro = cine.get("macro", {})
        shots = cine.get("shot_timeline", [])
        total_shots = macro.get("total_shots", len(shots))
        avg_shot = macro.get("avg_shot_length_sec", 0)

        # Get duration from last shot end
        duration = 0
        if shots:
            duration = shots[-1].get("end_sec", 0)
        metrics["total_duration_sec"] += duration

        # Cinematography
        metrics["total_shots"].append(total_shots)
        metrics["avg_shot_lengths"].append(avg_shot)
        if avg_shot > 0:
            metrics["asls"].append(avg_shot)
        if duration > 0:
            metrics["cut_freqs"].append(total_shots / duration)
        for s in shots:
            metrics["shot_types"][s.get("shot_type", "")] += 1
            metrics["camera_movements"][s.get("camera_movement", "")] += 1
            metrics["compositions"][s.get("framing", "")] += 1
            metrics["lightings"][s.get("lighting", "")] += 1
            metrics["transitions"][s.get("transition_to_next", "")] += 1
            h = s.get("camera_height_cm", 0)
            if h > 0:
                metrics["camera_heights"].append(h)

        # Audio
        audio = data.get("audio", {})
        amacro = audio.get("macro", {})
        vos = audio.get("voiceover_transcript", [])
        sfx = audio.get("sfx_timeline", [])
        bgm = audio.get("bgm_timeline", [])
        # 契约字段为 ducking_and_silence（prompts.json 与实际产出），silence_moments 为旧键兜底
        silence = audio.get("ducking_and_silence", audio.get("silence_moments", []))

        metrics["vo_counts"].append(len(vos))
        metrics["sfx_counts"].append(len(sfx))
        metrics["bgm_counts"].append(len(bgm))
        metrics["silence_counts"].append(len(silence))

        vo_ratio = amacro.get("voiceover_ratio_pct", 0)
        if vo_ratio > 0:
            metrics["vo_ratios"].append(vo_ratio)
        if duration > 0:
            metrics["sfx_density"].append(len(sfx) / duration * 10)

        metrics["bgm_genres"][amacro.get("bgm_genre", "")] += 1

        for vo in (vos if isinstance(vos, list) else []):
            if isinstance(vo, dict):
                metrics["speakers"][vo.get("speaker", "")] += 1
                metrics["tones"][vo.get("tone", "")] += 1

        # Narrative
        narr = data.get("narrative", {})
        if not isinstance(narr, dict): narr = {}
        nmacro = narr.get("macro", {})
        if not isinstance(nmacro, dict): nmacro = {}
        emos = narr.get("emotional_timeline", [])
        beats = narr.get("story_beats", [])
        quotes = narr.get("all_quotes", [])

        if isinstance(emos, list):
            metrics["emo_segments"].append(len(emos))
        if isinstance(beats, list):
            for b in beats:
                if isinstance(b, dict):
                    metrics["story_beats"][b.get("beat_type", "")] += 1

        # Hook analysis：优先读 hook_analysis.hook_type；缺失时从 story_beats 的 hook 节拍派生兜底
        hook = narr.get("hook_analysis", {})
        hook_type = hook.get("hook_type", "") if isinstance(hook, dict) else ""
        if not hook_type and isinstance(beats, list):
            hook_beat = next((b for b in beats if isinstance(b, dict) and b.get("beat_type") == "hook"), None)
            if hook_beat:
                desc = str(hook_beat.get("description", ""))
                desc = desc[:24] + "…" if len(desc) > 24 else desc
                hook_type = f"未标注(派生: {desc})" if desc else "未标注"
        if hook_type:
            metrics["hook_types"][hook_type] += 1

        if isinstance(quotes, list):
            metrics["quote_count"] += len(quotes)
            metrics["pun_count"] += sum(1 for q in quotes if isinstance(q, dict) and q.get("pun", False))
        metrics["narrative_templates"][nmacro.get("narrative_template", "")] += 1

        # AI/FX
        aifx = data.get("ai_fx", {})
        if isinstance(aifx, dict):
            scene_tl = aifx.get("scene_timeline", [])
            if isinstance(scene_tl, list):
                for scene in scene_tl:
                    if isinstance(scene, dict):
                        metrics["techniques"][scene.get("technique", "")] += 1
                        metrics["tool_guesses"][scene.get("tool_guess", "")] += 1
            fa = aifx.get("facial_animation", {})
            if isinstance(fa, dict):
                mmr = fa.get("micro_motion_ratio_pct", 0)
                if isinstance(mmr, (int, float)) and mmr > 0:
                    metrics["micro_motion_ratios"].append(mmr)

        # SOP
        sop = data.get("sop", {})
        if isinstance(sop, dict):
            pc = sop.get("production_complexity", {})
            if isinstance(pc, dict):
                metrics["complexity_ratings"][pc.get("complexity_rating", "")] += 1
                metrics["software_chains"][pc.get("software_chain", "")] += 1
            brands = sop.get("brand_elements", [])
            if isinstance(brands, list):
                metrics["brand_count"] += len(brands)

    # Calculate averages
    metrics["avg_duration_sec"] = metrics["total_duration_sec"] / max(len(all_data), 1)

    return metrics


def fmt_range(values):
    """格式化数值区间。"""
    if not values:
        return "N/A"
    return f"{min(values):.1f}-{max(values):.1f}"


def fmt_counter(counter, n=3):
    """把 Counter 格式化为自然语言（防 Python tuple repr 泄漏进 Markdown）。"""
    if not counter:
        return "无"
    items = [f"{k}({v}次)" for k, v in counter.most_common(n) if k]
    return ", ".join(items) if items else "无"


def fmt_avg(values):
    """格式化平均值。"""
    if not values:
        return "N/A"
    return f"{statistics.mean(values):.1f}"


def fmt_median(values):
    """格式化中位数。"""
    if not values:
        return "N/A"
    return f"{statistics.median(values):.1f}"


def generate_report(account, metrics, date_str):
    """生成 Markdown 报告。"""
    lines = []
    lines.append(f"# {account} · 账号级公式提炼报告")
    lines.append(f"\n> 分析日期: {date_str} | 视频数: {metrics['video_count']} | 总时长: {metrics['total_duration_sec']:.0f}s | 均时长: {metrics['avg_duration_sec']:.1f}s\n")

    # ── 镜头语言公式 ──
    lines.append("## 一、镜头语言公式\n")
    lines.append(f"| 指标 | 区间 | 均值 | 中位数 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| 总镜数 | {fmt_range(metrics['total_shots'])} | {fmt_avg(metrics['total_shots'])} | {fmt_median(metrics['total_shots'])} |")
    lines.append(f"| 平均镜长 (ASL) | {fmt_range(metrics['asls'])}s | {fmt_avg(metrics['asls'])}s | {fmt_median(metrics['asls'])}s |")
    lines.append(f"| 切频 (镜/秒) | {fmt_range(metrics['cut_freqs'])} | {fmt_avg(metrics['cut_freqs'])} | {fmt_median(metrics['cut_freqs'])} |")
    lines.append(f"| 机位高度 (cm) | {fmt_range(metrics['camera_heights'])} | {fmt_avg(metrics['camera_heights'])} | {fmt_median(metrics['camera_heights'])} |")

    # 主导技术
    lines.append(f"\n**主导镜头技术**:\n")
    for name, counter in [("景别", metrics["shot_types"]), ("运镜", metrics["camera_movements"]),
                          ("构图", metrics["compositions"]), ("光影", metrics["lightings"]),
                          ("转场", metrics["transitions"])]:
        top = counter.most_common(3)
        top_str = ", ".join(f"{k}({v}次)" for k, v in top if k)
        lines.append(f"- {name}: {top_str}")

    # ── 声音工程公式 ──
    lines.append(f"\n## 二、声音工程公式\n")
    lines.append(f"| 指标 | 区间 | 均值 |")
    lines.append(f"|---|---|---|")
    lines.append(f"| VO 条数 | {fmt_range(metrics['vo_counts'])} | {fmt_avg(metrics['vo_counts'])} |")
    lines.append(f"| SFX 条数 | {fmt_range(metrics['sfx_counts'])} | {fmt_avg(metrics['sfx_counts'])} |")
    lines.append(f"| BGM 变化数 | {fmt_range(metrics['bgm_counts'])} | {fmt_avg(metrics['bgm_counts'])} |")
    lines.append(f"| 停顿数 | {fmt_range(metrics['silence_counts'])} | {fmt_avg(metrics['silence_counts'])} |")
    lines.append(f"| VO 占比 % | {fmt_range(metrics['vo_ratios'])} | {fmt_avg(metrics['vo_ratios'])} |")
    lines.append(f"| SFX 密度 (条/10s) | {fmt_range(metrics['sfx_density'])} | {fmt_avg(metrics['sfx_density'])} |")

    lines.append(f"\n**声画结构**:\n")
    lines.append(f"- 主BGM风格: {fmt_counter(metrics['bgm_genres'])}")
    lines.append(f"- 说话者分布: {fmt_counter(metrics['speakers'])}")
    lines.append(f"- 语气分布: {fmt_counter(metrics['tones'])}")

    # ── 叙事公式 ──
    lines.append(f"\n## 三、叙事结构公式\n")
    lines.append(f"| 指标 | 区间 | 均值 |")
    lines.append(f"|---|---|---|")
    lines.append(f"| 情绪段数 | {fmt_range(metrics['emo_segments'])} | {fmt_avg(metrics['emo_segments'])} |")
    lines.append(f"- 故事节拍分布: {fmt_counter(metrics['story_beats'], 5)}")
    lines.append(f"- Hook 类型: {fmt_counter(metrics['hook_types'])}")
    lines.append(f"- 金句总数: {metrics['quote_count']} (双关: {metrics['pun_count']})")

    # ── AI/合成技术 ──
    lines.append(f"\n## 四、AI/合成技术\n")
    lines.append(f"- 技术手法分布: {fmt_counter(metrics['techniques'], 5)}")
    lines.append(f"- 推测工具: {fmt_counter(metrics['tool_guesses'], 5)}")
    if metrics["micro_motion_ratios"]:
        lines.append(f"- 面部微动比例: {fmt_range(metrics['micro_motion_ratios'])}%")

    # ── 制作SOP ──
    lines.append(f"\n## 五、制作 SOP\n")
    lines.append(f"- 复杂度评级: {fmt_counter(metrics['complexity_ratings'])}")
    lines.append(f"- 软件链: {fmt_counter(metrics['software_chains'])}")
    lines.append(f"- 品牌植入次数: {metrics['brand_count']}")

    # ── 一句话公式 ──
    lines.append(f"\n## 六、一句话公式命名\n")
    top_shot = metrics["shot_types"].most_common(1)[0][0] if metrics["shot_types"] else ""
    top_move = metrics["camera_movements"].most_common(1)[0][0] if metrics["camera_movements"] else ""
    asl = fmt_median(metrics["asls"])
    top_speaker = metrics["speakers"].most_common(1)[0][0] if metrics["speakers"] else ""
    vo_ratio = fmt_avg(metrics["vo_ratios"])
    lines.append(f"「{top_shot}+{top_move}+ASL {asl}s+{top_speaker}{vo_ratio}%」")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="账号级报告自动汇聚引擎")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", required=True, help="账号名")
    parser.add_argument("--date", help="只汇聚指定日期的分析文件")
    args = parser.parse_args()

    date_str = args.date or date.today().isoformat()
    all_data, videos_dir = load_account(args.archive_dir, args.account, args.date)

    if not all_data:
        print(f"未找到 {args.account} 的分析文件")
        sys.exit(1)

    print(f"加载 {len(all_data)} 个视频分析文件")

    metrics = extract_metrics(all_data)
    report = generate_report(args.account, metrics, date_str)

    output_path = Path(args.archive_dir) / args.account / f"account_formula_{date_str}.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"报告已生成: {output_path}")

    # 回写全局账号索引（formula 命名 + ASL 均值，供 Layer 1 baseline 注入）
    try:
        top_shot = metrics["shot_types"].most_common(1)[0][0] if metrics["shot_types"] else ""
        top_move = metrics["camera_movements"].most_common(1)[0][0] if metrics["camera_movements"] else ""
        asl_med = fmt_median(metrics["asls"])
        top_speaker = metrics["speakers"].most_common(1)[0][0] if metrics["speakers"] else ""
        formula_name = f"「{top_shot}+{top_move}+ASL {asl_med}s+{top_speaker}{fmt_avg(metrics['vo_ratios'])}%」"
        asl_mean = round(statistics.mean(metrics["asls"]), 2) if metrics["asls"] else None
        upsert_index(args.archive_dir, args.account,
                     formula_name=formula_name,
                     asl_mean=asl_mean)
        print("全局索引 _index.json 已回写（formula_name/asl_mean）")
    except Exception as e:
        print(f"⚠️ _index.json 回写失败（不阻断报告）: {e}")

    print(f"\n报告预览:\n{'='*60}")
    print(report[:2000])


if __name__ == "__main__":
    main()
