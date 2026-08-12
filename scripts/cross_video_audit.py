#!/usr/bin/env python3
"""跨视频内容雷同检测工具 —— 检测同类字段在不同视频间的描述是否雷同。

用法:
  python cross_video_audit.py --archive-dir /path/to/archive
  python cross_video_audit.py --archive-dir /path/to/archive --account "kat-and-oliver"

检测维度:
  1. SFX description 跨视频雷同（去掉视频名后是否唯一）
  2. VO text 跨视频雷同（同一账号内开头文本是否相同）
  3. BGM description 跨视频雷同
  4. visual_content 跨视频雷同
  5. emotional_timeline trigger 跨视频雷同
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def strip_video_name(text):
    """去掉 《xxx》 视频名前缀，只比较核心内容。"""
    return re.sub(r'《[^》]+》', '', text).strip()


def collect_fields(archive_dir, accounts=None):
    """从所有分析文件中收集待检测的文本字段。"""
    archive = Path(archive_dir)
    
    fields = {
        "sfx_desc": [],        # (account, video, sfx_type, core_desc)
        "vo_text": [],         # (account, video, text_prefix)
        "bgm_desc": [],        # (account, video, change_type, core_desc)
        "visual_content": [],  # (account, video, shot_index, core_vc)
        "emo_trigger": [],     # (account, video, core_trigger)
    }
    
    if accounts:
        acct_dirs = [archive / a for a in accounts]
    else:
        acct_dirs = [d for d in archive.iterdir() if d.is_dir() and not d.name.startswith('.') and not d.name.startswith('_')]
    
    for acct_dir in sorted(acct_dirs):
        acct = acct_dir.name
        videos_dir = acct_dir / "videos"
        if not videos_dir.exists():
            continue
        
        for f in sorted(videos_dir.glob("*/analysis_*.json")):
            vid = f.parent.name
            try:
                data = json.loads(f.read_text("utf-8"))
            except Exception:
                continue
            
            # SFX
            audio = data.get("audio", {})
            if isinstance(audio, dict):
                for item in audio.get("sfx_timeline", []):
                    if isinstance(item, dict):
                        desc = item.get("description", "")
                        typ = item.get("type", "")
                        fields["sfx_desc"].append((acct, vid, typ, strip_video_name(desc)))
                
                # VO
                for item in audio.get("voiceover_transcript", []):
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        fields["vo_text"].append((acct, vid, text[:50]))
                
                # BGM
                for item in audio.get("bgm_timeline", []):
                    if isinstance(item, dict):
                        desc = item.get("description", "")
                        ct = item.get("change_type", "")
                        fields["bgm_desc"].append((acct, vid, ct, strip_video_name(desc)))
            
            # visual_content
            cine = data.get("cinematography", {})
            if isinstance(cine, dict):
                for i, item in enumerate(cine.get("shot_timeline", [])):
                    if isinstance(item, dict):
                        vc = item.get("visual_content", "")
                        fields["visual_content"].append((acct, vid, i, strip_video_name(vc)))
            
            # emotional trigger
            narr = data.get("narrative", {})
            if isinstance(narr, dict):
                for item in narr.get("emotional_timeline", []):
                    if isinstance(item, dict):
                        trigger = item.get("trigger", "")
                        fields["emo_trigger"].append((acct, vid, strip_video_name(trigger)))
    
    return fields


def audit_field(name, entries, min_unique_ratio=0.3, min_dup_to_report=3):
    """审计一个字段的跨视频唯一性。"""
    total = len(entries)
    if total == 0:
        print(f"\n  {name}: 无数据")
        return
    
    cores = [e[-1] for e in entries]
    unique = len(set(cores))
    ratio = unique / total * 100 if total > 0 else 0
    
    status = "✅" if ratio >= min_unique_ratio * 100 else "❌"
    print(f"\n  {status} {name}")
    print(f"    总条目: {total} | 唯一值: {unique} ({ratio:.1f}%)")
    
    if ratio < min_unique_ratio * 100:
        counter = Counter(cores)
        print(f"    重复 Top {min(10, len(counter))}:")
        for desc, count in counter.most_common(10):
            if count >= min_dup_to_report:
                accounts = set(e[0] for e in entries if e[-1] == desc)
                print(f"      [{count}次, {len(accounts)}账号] {desc[:70]}")


def audit_vo_openings(entries):
    """专门检查 VO 开头文本在同一账号内的重复。"""
    print(f"\n  VO 开头跨视频重复检查（同账号内）:")
    
    by_account = defaultdict(list)
    for acct, vid, prefix in entries:
        by_account[acct].append((vid, prefix))
    
    for acct, items in sorted(by_account.items()):
        prefix_counter = Counter(p for _, p in items)
        dups = [(p, c) for p, c in prefix_counter.most_common(5) if c > 1]
        if dups:
            print(f"    {acct} ({len(items)}条VO):")
            for prefix, count in dups:
                print(f"      [{count}次] {prefix[:60]}...")
        else:
            print(f"    {acct}: ✅ 无重复开头")


def main():
    parser = argparse.ArgumentParser(
        description="跨视频内容雷同检测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", help="只检测指定账号（可选）")
    args = parser.parse_args()
    
    accounts = [args.account] if args.account else None
    fields = collect_fields(args.archive_dir, accounts)
    
    total_videos = len(set(e[1] for entries in fields.values() for e in entries))
    
    print("=" * 70)
    print("跨视频内容雷同检测报告")
    print("=" * 70)
    
    audit_field("SFX description（去掉视频名后）", fields["sfx_desc"], min_unique_ratio=0.5)
    audit_field("BGM description（去掉视频名后）", fields["bgm_desc"], min_unique_ratio=0.5)
    audit_field("visual_content（去掉视频名后）", fields["visual_content"], min_unique_ratio=0.5)
    audit_field("emotional trigger（去掉视频名后）", fields["emo_trigger"], min_unique_ratio=0.3)
    audit_vo_openings(fields["vo_text"])
    
    # 汇总
    print(f"\n{'='*70}")
    print("汇总:")
    for name, entries in fields.items():
        if entries:
            cores = [e[-1] for e in entries]
            unique = len(set(cores))
            total = len(cores)
            ratio = unique / total * 100 if total > 0 else 0
            status = "✅" if ratio >= 50 else "❌"
            print(f"  {status} {name}: {unique}/{total} 唯一 ({ratio:.1f}%)")
    
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
