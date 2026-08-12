#!/usr/bin/env python3
"""
音效库体检器 — 对 _sfx_library/sfx_library.json 做结构与质量审计

背景：2026-07-28 archiver second 字段错位曾静默丢失 260 条（185→448 找回），
契约漂移是本库已知风险模式。本脚本提供定期体检，替代"靠事故发现"。

检查项：
  1. total_entries 字段与实际条目数对账
  2. 账号/类别分布
  3. 空字段率（description / sync_with_visual / category）
  4. 检索 tag 覆盖率（≤2 个 tag 视为弱标注）
  5. 时间戳异常：_sfx_0 残留（字段错位征兆）、越界（> 视频时长+容差）、负值
  6. 归档覆盖：盘上有 analysis JSON 但库中零条目的视频（漏归档）
  7. dedup_key 跨视频重复度（信息项，供模式聚合参考）

用法:
  python3 sfx_audit.py --archive-dir /path/to/对标视频分析资产
  # 报告落盘: <archive-dir>/_sfx_library/audit_report.md
  # 退出码: 0=无结构性问题(WARN 可有) 1=有结构性问题(对账不符/越界/漏归档)
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

TS_TOLERANCE_SEC = 1.0  # 越界容差，与 schema_contract honesty_view_duration_tolerance_sec 对齐


def load_video_durations(archive_dir):
    """扫描各账号 videos/*/ 的 _video_meta.json，返回 {video_id: duration_sec}"""
    durations = {}
    for meta_path in Path(archive_dir).glob("*/videos/*/_video_meta.json"):
        video_id = meta_path.parent.name
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            d = meta.get("duration_sec")
            if isinstance(d, (int, float)) and d > 0:
                durations[video_id] = float(d)
        except Exception:
            continue
    return durations


def load_analyzed_videos(archive_dir):
    """扫描盘上所有 analysis_*.json，返回 {video_id: (account, audio_ready)}
    audio_ready=False 表示 audio 板块为空（分析进行中/未完成，不算真漏归档）"""
    videos = {}
    for json_path in Path(archive_dir).glob("*/videos/*/analysis_*.json"):
        audio_ready = False
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            audio = data.get("audio", {})
            audio_ready = isinstance(audio, dict) and bool(
                audio.get("sfx_timeline") or audio.get("bgm_timeline")
            )
        except Exception:
            pass
        videos[json_path.parent.name] = (json_path.parts[-4], audio_ready)
    return videos


def audit(archive_dir):
    lib_path = os.path.join(archive_dir, "_sfx_library", "sfx_library.json")
    if not os.path.exists(lib_path):
        print(f"❌ 音效库不存在: {lib_path}")
        sys.exit(1)

    with open(lib_path, encoding="utf-8") as f:
        lib = json.load(f)
    entries = lib.get("entries", [])

    structural_issues = []  # 结构性问题（exit 1）
    warnings = []           # 质量警告（exit 0）

    # 1. 对账
    declared = lib.get("total_entries")
    if declared != len(entries):
        structural_issues.append(f"total_entries 字段 {declared} ≠ 实际条目数 {len(entries)}")

    # 2. 分布
    by_account = Counter(e.get("source_account", "?") for e in entries)
    by_category = Counter(e.get("category") or "(空)" for e in entries)
    by_video = Counter(e.get("source_video", "?") for e in entries)

    # 3. 空字段率（字段可能被 AI 产成 bool/数值，统一转字符串判空）
    def blank(v):
        return not str(v).strip() if v is not None and not isinstance(v, bool) else not bool(v)

    empty_desc = [e for e in entries if blank(e.get("description"))]
    empty_sync = [e for e in entries if blank(e.get("sync_with_visual"))]
    empty_cat = [e for e in entries if blank(e.get("category"))]
    nonstr_fields = [e.get("sfx_id") for e in entries
                     if any(not isinstance(e.get(k), str) and e.get(k) is not None
                            for k in ("description", "sync_with_visual", "category", "sfx_name", "type"))]
    if nonstr_fields:
        warnings.append(f"非字符串文本字段（bool/数值污染，P1 打标时归一）: {len(nonstr_fields)} 条 — {nonstr_fields[:5]}")
    if empty_desc:
        warnings.append(f"description 为空: {len(empty_desc)} 条 ({len(empty_desc)*100//len(entries)}%)")
    if empty_cat:
        warnings.append(f"category 为空: {len(empty_cat)} 条")

    # 4. tag 覆盖率
    tag_dist = Counter(len(e.get("search_tags", [])) for e in entries)
    weak_tag = sum(c for n, c in tag_dist.items() if n <= 2)
    if weak_tag:
        warnings.append(f"弱标注（≤2 个 tag）: {weak_tag} 条 ({weak_tag*100//len(entries)}%)")

    # 5. 时间戳异常
    durations = load_video_durations(archive_dir)
    zero_ts = defaultdict(list)   # video -> [sfx_id] 时间戳为 0（_sfx_0 残留征兆）
    out_of_range = []
    negative_ts = []
    no_duration = set()
    for e in entries:
        ts = e.get("timestamp_sec", 0)
        vid = e.get("source_video", "?")
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            structural_issues.append(f"非数值时间戳: {e.get('sfx_id')} = {ts!r}")
            continue
        if ts == 0:
            zero_ts[vid].append(e.get("sfx_id", "?"))
        if ts < 0:
            negative_ts.append(e.get("sfx_id", "?"))
        dur = durations.get(vid)
        if dur is None:
            no_duration.add(vid)
        elif ts > dur + TS_TOLERANCE_SEC:
            out_of_range.append(f"{e.get('sfx_id')} ts={ts} > 时长 {dur}")
    # 同一视频多条 0 时间戳 = 字段错位征兆（正常最多 sfx/bgm/duck 各 1 条真 0 开头）
    suspicious_zero = {v: ids for v, ids in zero_ts.items() if len(ids) > 3}
    if suspicious_zero:
        structural_issues.append(
            f"疑似字段错位（单视频 >3 条 0 时间戳）: {len(suspicious_zero)} 个视频 — "
            + "; ".join(f"{v}({len(ids)}条)" for v, ids in list(suspicious_zero.items())[:5])
        )
    if negative_ts:
        structural_issues.append(f"负时间戳: {len(negative_ts)} 条 — {negative_ts[:5]}")
    if out_of_range:
        structural_issues.append(f"时间戳越界（>时长+{TS_TOLERANCE_SEC}s）: {len(out_of_range)} 条 — " + "; ".join(out_of_range[:5]))
    if no_duration:
        warnings.append(f"缺 _video_meta.json 时长、越界检查跳过: {len(no_duration)} 个视频 — {sorted(no_duration)[:5]}")

    # 6. 归档覆盖（audio 板块已就绪才算真漏归档；未就绪=分析进行中，仅提示）
    analyzed = load_analyzed_videos(archive_dir)
    missing = {v: a for v, (a, ready) in analyzed.items() if v not in by_video and ready}
    in_progress = {v: a for v, (a, ready) in analyzed.items() if v not in by_video and not ready}
    if missing:
        structural_issues.append(
            f"盘上有完整 analysis JSON 但库中零条目（漏归档）: {len(missing)} 个视频 — "
            + "; ".join(f"{a}/{v}" for v, a in sorted(missing.items())[:8])
        )
    if in_progress:
        warnings.append(f"分析进行中（audio 板块未就绪，不计漏归档）: {len(in_progress)} 个视频 — {sorted(in_progress)[:5]}")
    orphan = {v for v in by_video if v not in analyzed}
    if orphan:
        warnings.append(f"库中有条目但盘上无 analysis JSON（源已移动/删除）: {len(orphan)} 个视频 — {sorted(orphan)[:5]}")

    # 7. dedup_key 跨视频重复（信息项）
    key_videos = defaultdict(set)
    for e in entries:
        key_videos[e.get("dedup_key", "?")].add(e.get("source_video"))
    cross = {k: vs for k, vs in key_videos.items() if len(vs) > 1}

    # ---- 报告 ----
    lines = []
    lines.append("# 音效库体检报告")
    lines.append("")
    lines.append(f"- 体检时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 库路径: `{lib_path}`")
    lines.append(f"- 条目数: {len(entries)}（声明 {declared}）")
    lines.append(f"- 覆盖视频: 库内 {len(by_video)} / 盘上已分析 {len(analyzed)}")
    lines.append(f"- 结论: {'❌ 有结构性问题' if structural_issues else '✅ 无结构性问题'}"
                 f"{f'，{len(warnings)} 项质量警告' if warnings else ''}")
    lines.append("")
    if structural_issues:
        lines.append("## ❌ 结构性问题（阻塞打标，须先修复）")
        lines.append("")
        for s in structural_issues:
            lines.append(f"- {s}")
        lines.append("")
    if warnings:
        lines.append("## ⚠️ 质量警告（不阻塞，P1 打标可顺带修复）")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    lines.append("## 账号分布")
    lines.append("")
    lines.append("| 账号 | 条目 | 视频数 |")
    lines.append("|---|---|---|")
    vid_per_account = defaultdict(set)
    for e in entries:
        vid_per_account[e.get("source_account", "?")].add(e.get("source_video"))
    for acc, n in by_account.most_common():
        lines.append(f"| {acc} | {n} | {len(vid_per_account[acc])} |")
    lines.append("")
    lines.append("## 类别分布")
    lines.append("")
    lines.append("| category | 条目 |")
    lines.append("|---|---|")
    for cat, n in by_category.most_common():
        lines.append(f"| {cat} | {n} |")
    lines.append("")
    lines.append("## tag 数量分布")
    lines.append("")
    lines.append("| tag 数 | 条目 |")
    lines.append("|---|---|")
    for n in sorted(tag_dist):
        lines.append(f"| {n} | {tag_dist[n]} |")
    lines.append("")
    lines.append("## dedup_key 跨视频重复（模式聚合参考）")
    lines.append("")
    lines.append(f"- 跨 ≥2 个视频的 dedup_key: {len(cross)} 个（共 {len(key_videos)} 个 key）")
    top_cross = sorted(cross.items(), key=lambda kv: -len(kv[1]))[:10]
    for k, vs in top_cross:
        lines.append(f"  - `{k}` × {len(vs)} 视频")
    lines.append("")

    report_path = os.path.join(archive_dir, "_sfx_library", "audit_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n".join(lines))
    print(f"\n报告已落盘: {report_path}")
    return 1 if structural_issues else 0


def main():
    parser = argparse.ArgumentParser(description="音效库体检器")
    parser.add_argument("--archive-dir", required=True, help="归档根目录（对标视频分析资产）")
    args = parser.parse_args()
    sys.exit(audit(args.archive_dir))


if __name__ == "__main__":
    main()
