#!/usr/bin/env python3
"""
视频目录构建器 — 从各视频 analysis JSON 聚合视频级元数据，供音效决策台消费

产出 _sfx_library/video_catalog.json，每条视频含：
  - video_id / account / title / duration_sec
  - beats: 归一化叙事节拍 [{beat, start_sec, end_sec}]（beat ∈ hook/setup/rising/climax/reversal/ending）
  - story_structure / narrative_template / hook_analysis（原文摘录，供人工/LLM 定类型参考）
  - video_type: 视频类型标签（本脚本置 null，由 LLM 打标回填；--merge-types 合并已有值不覆盖）

用法:
  python3 build_video_catalog.py --archive-dir /path/to/对标视频分析资产
  # 重跑时默认保留已回填的 video_type（--merge-types 默认开）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# beat_type 归一映射（2026-07-31 全库实测词形）
BEAT_NORMALIZE = {
    "hook": "hook", "setup": "setup", "rising_action": "rising",
    "rising action": "rising", "complication": "rising",
    "inciting incident": "rising", "climax": "climax",
    "climax & turning point": "climax", "reversal": "reversal",
    "ending": "ending", "resolution": "ending",
}


def normalize_beat(raw):
    if not isinstance(raw, str):
        return None
    key = re.sub(r"[（(].*?[)）]", "", raw).strip().lower()
    return BEAT_NORMALIZE.get(key)


def to_float(v):
    try:
        if isinstance(v, str):
            v = v.split("-")[0].strip()
        return float(v)
    except (TypeError, ValueError):
        return None


def build(archive_dir):
    catalog_path = os.path.join(archive_dir, "_sfx_library", "video_catalog.json")

    # 保留已回填的 video_type
    existing_types = {}
    if os.path.exists(catalog_path):
        try:
            with open(catalog_path, encoding="utf-8") as f:
                old = json.load(f)
            for v in old.get("videos", []):
                if v.get("video_type"):
                    existing_types[v["video_id"]] = v["video_type"]
        except Exception:
            pass

    videos = []
    # 同一视频目录可能有多份不同日期的 analysis_*.json，只取最新一份（文件名日期序）
    latest = {}
    for json_path in sorted(Path(archive_dir).glob("*/videos/*/analysis_*.json")):
        latest[json_path.parent] = json_path
    for parent, json_path in sorted(latest.items()):
        video_id = json_path.parent.name
        account = json_path.parts[-4]

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        # 时长：优先 _video_meta.json
        duration = None
        meta_path = json_path.parent / "_video_meta.json"
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    duration = to_float(json.load(f).get("duration_sec"))
            except Exception:
                pass

        narrative = data.get("narrative", {}) if isinstance(data.get("narrative"), dict) else {}
        audio = data.get("audio", {}) if isinstance(data.get("audio"), dict) else {}
        audio_ready = bool(audio.get("sfx_timeline") or audio.get("bgm_timeline"))

        beats = []
        for b in narrative.get("story_beats", []) or []:
            if not isinstance(b, dict):
                continue
            beat = normalize_beat(b.get("beat_type"))
            start = to_float(b.get("start_sec", b.get("second")))
            end = to_float(b.get("end_sec"))
            if beat and start is not None:
                beats.append({"beat": beat, "start_sec": start, "end_sec": end})
        beats.sort(key=lambda x: x["start_sec"])

        macro = narrative.get("macro", {}) if isinstance(narrative.get("macro"), dict) else {}
        # 标题取目录名去掉序号/平台ID前缀
        title = re.sub(r"^\d+-[A-Za-z0-9]+-", "", video_id)

        videos.append({
            "video_id": video_id,
            "account": account,
            "title": title,
            "duration_sec": duration,
            "audio_ready": audio_ready,
            "beats": beats,
            "story_structure": str(macro.get("story_structure") or "")[:200],
            "narrative_template": str(macro.get("narrative_template") or "")[:200],
            "hook_analysis": str(narrative.get("hook_analysis") or "")[:200],
            "video_type": existing_types.get(video_id),
        })

    catalog = {
        "version": "1.0",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_videos": len(videos),
        "type_vocab_note": "video_type 由 LLM 按词表回填；重跑本脚本不覆盖已回填值",
        "videos": videos,
    }
    os.makedirs(os.path.dirname(catalog_path), exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    typed = sum(1 for v in videos if v["video_type"])
    with_beats = sum(1 for v in videos if v["beats"])
    print(f"✅ video_catalog.json: {len(videos)} 条视频（beats 覆盖 {with_beats}，已定类型 {typed}）")
    print(f"   路径: {catalog_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="视频目录构建器")
    parser.add_argument("--archive-dir", required=True, help="归档根目录（对标视频分析资产）")
    args = parser.parse_args()
    sys.exit(build(args.archive_dir))


if __name__ == "__main__":
    main()
