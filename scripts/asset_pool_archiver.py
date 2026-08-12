#!/usr/bin/env python3
"""
音效库归档器 — 从视频分析 JSON 中提取音效，持续归档到音效库

音效库 (sfx_library.json)：
  - 从 audio.sfx_timeline 提取音效
  - 从 audio.bgm_timeline 提取 BGM 变化
  - 从 audio.ducking_and_silence 提取闪避事件
  - 自动生成音效库检索 tag
  - 跨视频去重，持续更新

用法:
  # 归档单个视频
  python3 asset_pool_archiver.py \
    --archive-dir /path/to/archive \
    --account "AccountD" \
    --video-id "SubjectBSubjectA_TOP01_7341470837029047595" \
    --date 2026-07-25

  # 归档账号下所有视频
  python3 asset_pool_archiver.py \
    --archive-dir /path/to/archive \
    --account "AccountD" \
    --all

  # 查看音效库统计
  python3 asset_pool_archiver.py \
    --archive-dir /path/to/archive \
    --stats
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def generate_sfx_search_tags(sfx_name, sfx_type, sfx_desc, category=""):
    """生成音效库检索 tag"""
    tags = set()

    if sfx_name:
        tags.add(sfx_name)
    if sfx_type:
        tags.add(sfx_type)
    if category:
        tags.add(category)

    combined = (sfx_name + " " + sfx_desc).lower()

    # 动物相关
    if any(kw in combined for kw in ["狗", "dog", "犬", "爪", "鼻", "尾巴", "耳朵"]):
        tags.add("animal_dog")
        if "爪" in combined:
            tags.add("dog_paw")
        if "鼻" in combined:
            tags.add("dog_nose")
        if "尾巴" in combined:
            tags.add("dog_tail")

    # 动作类
    if any(kw in combined for kw in ["脚步", "走", "跑", "step", "walk", "run"]):
        tags.add("footstep")
    if any(kw in combined for kw in ["关门", "砰", "door", "slam"]):
        tags.add("door_slam")
    if any(kw in combined for kw in ["叹气", "sigh", "huuu"]):
        tags.add("human_sigh")
    if any(kw in combined for kw in ["心跳", "heartbeat"]):
        tags.add("heartbeat")
    if any(kw in combined for kw in ["刹车", "brake"]):
        tags.add("car_brake")

    # 环境类
    if any(kw in combined for kw in ["环境", "ambient", "室内", "室外"]):
        tags.add("ambient_room")

    # 戏剧类
    if any(kw in combined for kw in ["戏剧", "dramatic", "反转", "悬念", "紧张", "凝视"]):
        tags.add("dramatic_sfx")

    return sorted(tags)


def parse_ts(item):
    """时间字段回退链 second→start_sec→timestamp_sec，并归一为 float。
    兼容区间字符串 "44.0-45.0"（取起点；2026-07-31 体检发现 duck 条目区间格式直接入库）"""
    raw = item.get("second", item.get("start_sec", item.get("timestamp_sec", 0)))
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        head = raw.split("-")[0].strip()
        try:
            return float(head)
        except ValueError:
            return 0.0
    return 0.0


def extract_sfx(data, video_id, account):
    """从分析 JSON 中提取音效"""
    sfx_entries = []

    audio = data.get("audio", {})

    # 1. SFX 时间轴
    for sfx in audio.get("sfx_timeline", []):
        # 名称回退链 name→sfx_name→type（2026-07-31 体检：AccountA型条目名称在 name 字段，
        # 旧逻辑只读 type 导致 152 条入库为 "foley"/"synthesized" 语义空壳，第 6 处契约错位）
        sfx_name = sfx.get("name", sfx.get("sfx_name", sfx.get("type", "")))
        sfx_type = sfx.get("type", "")
        sfx_desc = sfx.get("description", "")
        category = sfx.get("category", "")
        # AI 产出可能混入 bool/数值，统一归一为字符串（2026-07-31 体检：19 条污染）
        sfx_name = str(sfx_name) if sfx_name is not None and not isinstance(sfx_name, bool) else ""
        sfx_type = str(sfx_type) if sfx_type is not None and not isinstance(sfx_type, bool) else ""
        sfx_desc = str(sfx_desc) if sfx_desc is not None and not isinstance(sfx_desc, bool) else ""
        category = str(category) if category is not None and not isinstance(category, bool) else ""

        dedup_key = f"{sfx_type}_{(sfx_desc or sfx_name)[:20]}"
        search_tags = generate_sfx_search_tags(sfx_name, sfx_type, sfx_desc, category)

        # 时间字段回退+区间归一（2026-07-28：start_sec 型条目 id 全为 _sfx_0 被去重吐掉；2026-07-31：区间字符串）
        sfx_ts = parse_ts(sfx)
        entry = {
            "sfx_id": f"{video_id}_sfx_{sfx_ts}",
            "source_video": video_id,
            "source_account": account,
            "timestamp_sec": sfx_ts,
            "sfx_name": sfx_name,
            "type": sfx_type,
            "category": category,
            "description": sfx_desc,
            # 源字段可能为 bool（仅表示是否同步），归一为字符串
            "sync_with_visual": (lambda v: "true" if v is True else "" if v is False or v is None else str(v))(sfx.get("sync_with_visual", sfx.get("triad_coupling"))),
            "search_tags": search_tags,
            "dedup_key": dedup_key,
            "archived_date": datetime.now().strftime("%Y-%m-%d"),
        }
        sfx_entries.append(entry)

    # 2. BGM 时间轴
    for bgm in audio.get("bgm_timeline", []):
        change_type = bgm.get("change_type", "")
        genre = bgm.get("genre", "")
        desc = bgm.get("description", "")

        bgm_ts = parse_ts(bgm)
        entry = {
            "sfx_id": f"{video_id}_bgm_{bgm_ts}",
            "source_video": video_id,
            "source_account": account,
            "timestamp_sec": bgm_ts,
            "sfx_name": f"BGM_{change_type}",
            "type": "BGM变化",
            "category": "背景音乐",
            "description": desc,
            "sync_with_visual": "",
            "search_tags": sorted(set([f"bgm_{change_type}", genre, "background_music"] if genre else [f"bgm_{change_type}", "background_music"])),
            "dedup_key": f"BGM_{change_type}_{genre}",
            "archived_date": datetime.now().strftime("%Y-%m-%d"),
        }
        sfx_entries.append(entry)

    # 3. Ducking / 静音事件
    ducking_list = audio.get("ducking_and_silence", audio.get("silence_moments", []))
    # 软字段(top_soft)：AI 可能产出字符串/单对象，归一为字典列表，非结构化则置空
    if isinstance(ducking_list, dict):
        ducking_list = [ducking_list]
    elif not isinstance(ducking_list, list):
        ducking_list = []
    for duck in ducking_list:
        if not isinstance(duck, dict):
            continue
        effect = duck.get("effect", duck.get("type", ""))
        trigger = duck.get("trigger_event", duck.get("trigger_source", ""))

        duck_ts = parse_ts(duck)
        entry = {
            "sfx_id": f"{video_id}_duck_{duck_ts}",
            "source_video": video_id,
            "source_account": account,
            "timestamp_sec": duck_ts,
            "sfx_name": f"Ducking_{effect[:20]}",
            "type": "Ducking/静音",
            "category": "音频闪避",
            "description": f"效果: {effect}, 触发: {trigger}, 衰减: {duck.get('ducking_attenuation_db', duck.get('reduction_db', 'N/A'))}dB, 持续: {duck.get('duration_sec', duck.get('duration_ms', 'N/A'))}s",
            "sync_with_visual": trigger,
            "search_tags": sorted(set(["ducking", "silence", f"ducking_{effect[:10]}"])),
            "dedup_key": f"ducking_{effect[:20]}",
            "archived_date": datetime.now().strftime("%Y-%m-%d"),
        }
        sfx_entries.append(entry)

    return sfx_entries


def load_pool(pool_path):
    """加载音效库（如果存在）"""
    if os.path.exists(pool_path):
        with open(pool_path, encoding="utf-8") as f:
            return json.load(f)
    return {"version": "1.0", "last_updated": "", "total_entries": 0, "entries": []}


def save_pool(pool_path, pool):
    """保存音效库"""
    pool["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pool["total_entries"] = len(pool["entries"])

    os.makedirs(os.path.dirname(pool_path), exist_ok=True)
    with open(pool_path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

    return pool["total_entries"]


def merge_entries(existing_entries, new_entries, dedup_key="sfx_id"):
    """合并条目，去重"""
    existing_keys = {e.get(dedup_key, "") for e in existing_entries}

    added = 0
    updated = 0

    for entry in new_entries:
        key = entry.get(dedup_key, "")
        if key in existing_keys:
            for i, e in enumerate(existing_entries):
                if e.get(dedup_key, "") == key:
                    for k, v in entry.items():
                        if k != dedup_key:
                            if k not in e or not e[k]:
                                e[k] = v
                    updated += 1
                    break
        else:
            existing_entries.append(entry)
            existing_keys.add(key)
            added += 1

    return existing_entries, added, updated


def main():
    parser = argparse.ArgumentParser(description="音效库归档器")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", help="账号名")
    parser.add_argument("--video-id", help="视频ID")
    parser.add_argument("--date", help="分析日期 YYYY-MM-DD")
    parser.add_argument("--all", action="store_true", help="归档账号下所有视频")
    parser.add_argument("--rebuild", action="store_true",
                        help="重灌模式：先删除本批视频在库中的旧条目再入库（清理字段错位残留/ID 格式漂移，幂等）")
    parser.add_argument("--stats", action="store_true", help="仅显示音效库统计")
    args = parser.parse_args()

    archive_dir = args.archive_dir
    sfx_library_path = os.path.join(archive_dir, "_sfx_library", "sfx_library.json")

    # 统计模式
    if args.stats:
        print("=" * 60)
        print("音效库统计")
        print("=" * 60)

        pool = load_pool(sfx_library_path)
        print(f"\n📊 音效库")
        print(f"   路径: {sfx_library_path}")
        print(f"   总条目: {pool.get('total_entries', 0)}")
        print(f"   最后更新: {pool.get('last_updated', 'N/A')}")

        entries = pool.get("entries", [])
        if entries:
            sources = {}
            for e in entries:
                acct = e.get("source_account", "unknown")
                sources[acct] = sources.get(acct, 0) + 1
            print(f"   来源账号: {dict(sorted(sources.items(), key=lambda x: -x[1]))}")

            categories = {}
            for e in entries:
                cat = e.get("category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1
            print(f"   分类: {dict(sorted(categories.items(), key=lambda x: -x[1]))}")

            dedup_keys = {e.get("dedup_key", "") for e in entries}
            print(f"   去重后唯一音效: {len(dedup_keys)}")

            # 列出所有检索 tag
            all_tags = set()
            for e in entries:
                all_tags.update(e.get("search_tags", []))
            print(f"   检索 tag 数: {len(all_tags)}")
        return

    # 确定要归档的视频列表
    videos_to_archive = []

    if args.all:
        if not args.account:
            print("❌ --all 模式需要 --account 参数")
            sys.exit(1)

        videos_dir = Path(archive_dir) / args.account / "videos"
        if not videos_dir.exists():
            print(f"❌ 账号目录不存在: {videos_dir}")
            sys.exit(1)

        for json_file in sorted(videos_dir.glob("*/analysis_*.json")):
            video_id = json_file.parent.name
            date = json_file.stem.replace("analysis_", "")
            videos_to_archive.append((video_id, date, json_file))
        # 同视频多份分析 JSON 只取最新日期，避免新旧版条目混入（2026-07-31：AccountA 02/03 双版共存）
        latest = {}
        for video_id, date, json_file in videos_to_archive:
            if video_id not in latest or date > latest[video_id][1]:
                latest[video_id] = (video_id, date, json_file)
        videos_to_archive = sorted(latest.values())
    else:
        if not args.account or not args.video_id:
            print("❌ 需要 --account 和 --video-id 参数")
            sys.exit(1)

        date = args.date or datetime.now().strftime("%Y-%m-%d")
        json_path = os.path.join(archive_dir, args.account, "videos", args.video_id, f"analysis_{date}.json")

        if not os.path.exists(json_path):
            print(f"❌ 分析文件不存在: {json_path}")
            sys.exit(1)

        videos_to_archive.append((args.video_id, date, Path(json_path)))

    print("=" * 60)
    print("音效库归档")
    print(f"归档视频数: {len(videos_to_archive)}")
    print("=" * 60)

    # 加载音效库
    sfx_library = load_pool(sfx_library_path)

    total_sfx_added = 0
    total_sfx_updated = 0

    for video_id, date, json_path in videos_to_archive:
        print(f"\n📂 处理: {video_id} ({date})")

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        # 重灌模式：先清除该视频旧条目，避免错位残留/ID 格式漂移造成的僵尸条目
        if args.rebuild:
            before = len(sfx_library["entries"])
            sfx_library["entries"] = [e for e in sfx_library["entries"] if e.get("source_video") != video_id]
            removed = before - len(sfx_library["entries"])
            if removed:
                print(f"   重灌: 删除旧条目 {removed} 条")

        # 提取音效
        sfx_entries = extract_sfx(data, video_id, args.account)
        print(f"   提取音效: {len(sfx_entries)} 条")

        # 合并到音效库
        sfx_library["entries"], s_added, s_updated = merge_entries(
            sfx_library["entries"], sfx_entries, "sfx_id"
        )
        total_sfx_added += s_added
        total_sfx_updated += s_updated
        print(f"   音效库: +{s_added} 新增, ~{s_updated} 更新")

    # 保存音效库
    sfx_count = save_pool(sfx_library_path, sfx_library)

    print(f"\n{'=' * 60}")
    print(f"✅ 归档完成")
    print(f"   音效库: {sfx_count} 条 (+{total_sfx_added} 新增, ~{total_sfx_updated} 更新)")
    print(f"{'=' * 60}")
    print(f"\n音效库路径: {sfx_library_path}")


if __name__ == "__main__":
    main()
