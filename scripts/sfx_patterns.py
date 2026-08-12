#!/usr/bin/env python3
"""
音效模式聚合器 — 从 sfx_library_v2.json 聚合出跨视频"音效模式"层

按语义家族词典（确定性关键词聚类）把 885 条原始条目收敛为音效模式，每个模式含：
  - freq / video_count / account_count（头部共识强度）
  - position_histogram: 0-100% 进度 10 桶直方图（时机分布）
  - stage_dist / scene_dist / emotion_dist / coupling_dist（四维分布）
  - typical_params: ducking 衰减 dB 等（音频闪避族）
  - supply_status: 待录(映射声音库需求清单 S01-S05) / 可AI生成
  - examples: 代表用例（description 最丰富的 TopN，带回看定位）

未命中家族的条目落入 "其他·<类别>" 兜底模式，保证 100% 覆盖。
产出: _sfx_library/sfx_patterns.json

用法:
  python3 sfx_patterns.py --archive-dir /path/to/对标视频分析资产
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

# 语义家族词典（2026-07-31 按全库词根实测归纳；顺序即优先级，先匹配先归属）
FAMILIES = [
    # (family_id, 名称, 关键词, supply_status, 需求清单映射)
    ("char_dog_voice", "狗狗叫声/哼唧", ["哼唧", "呜咽", "犬吠", "狗叫", "汪", "吠", "狗狗喘", "狗喘"], "待录", "S01_角色音"),
    ("char_cat_voice", "猫咪叫声", ["猫叫", "喵", "嗷呜", "猫咪大", "呼噜"], "待录", "S01_角色音"),
    ("char_breath", "呼吸/喘息/打呼", ["呼吸", "喘息", "打呼", "呼噜声", "叹气", "打嗝", "饱嗝"], "待录", "S01_角色音"),
    ("paw_steps", "脚步/爪步声", ["脚步", "爪步", "踏声", "踏地", "跑声", "奔跑", "爪子拍", "猫爪拍", "踩", "踏雪", "高跟鞋"], "待录", "S02_爪子地面"),
    ("fabric_friction", "布料/毛发摩擦", ["布料", "衣物", "皮衣摩", "摩擦声", "摩擦音", "蹭", "沙沙", "抓挠"], "待录", "S03_布料摩擦"),
    ("door", "开关门/门把", ["关门", "开门", "门把", "门声", "木门", "门铃", "敲门", "吱呀", "door", "creak"], "待录", "S04_物件停顿"),
    ("glass_tableware", "玻璃/餐具碰撞", ["玻璃杯", "玻璃碰", "餐具", "碗", "瓷", "杯子", "clink", "食盆"], "待录", "S04_物件停顿"),
    ("paper", "纸张/翻页", ["纸张", "翻页", "翻动", "书页", "纸片", "小票", "翻书"], "待录", "S04_物件停顿"),
    ("impact", "撞击/碰撞重音", ["撞击", "撞声", "碰撞", "砸", "咚", "砰", "闷响", "重音", "坠落", "掉落", "thud", "slam", "压陷"], "待录", "S04_物件停顿"),
    ("toy_squeak", "玩具发声/哨音", ["玩具", "软胶", "squeak", "哔哔", "哨音", "高音笛", "发声玩具"], "待录", "S04_物件停顿"),
    ("music_sting", "音乐插入/情绪乐句", ["情歌", "交响乐", "手风琴", "saxophone", "音乐渐入", "唱段", "乐曲", "琴声", "音乐骤停", "BGM 骤停", "弹拨"], "可补录/外采", None),
    ("metal_mech", "金属/机械", ["金属", "链条", "咔哒", "机械", "锁", "钥匙", "刀具", "剑", "拔剑", "头盔", "电机", "滑轨", "chain", "key", "click", "cock"], "可补录/外采", None),
    ("keyboard", "键盘/打字", ["键盘", "打字", "按键盘", "typing"], "可补录/外采", None),
    ("ui_notify", "手机/UI提示音", ["提示音", "通知", "叮咚", "手机提", "短信", "App", "按键", "触屏", "POS", "车机", "语音播报"], "可补录/外采", None),
    ("chew_eat", "咀嚼/进食", ["咀嚼", "嚼音", "进食", "吞咽", "舔", "吃", "啃", "lick"], "待录", "S01_角色音"),
    ("water", "水声", ["水流", "浇水", "淋浴", "水声", "滋滋水", "喷水", "水龙头", "splash", "浴室水"], "待录", "S05_环境底噪"),
    ("bell", "铃铛/摇铃", ["铃铛", "摇铃", "铃声", "风铃", "叮当"], "待录", "S04_物件停顿"),
    ("cartoon_accent", "卡通强调音", ["感叹号", "闪光", "弹簧", "变身", "动漫", "卡通", "二次元", "噔", "锵", "夸张", "comic", "pop", "sting"], "可补录/外采", None),
    ("suspense", "悬念/心跳/警报", ["心跳", "警报", "悬念", "紧张", "蜂鸣", "嗡嗡", "heartbeat", "alarm"], "可补录/外采", None),
    ("whoosh", "风声/嗖嗖/转场", ["嗖嗖", "风声", "whoosh", "破风", "挥砍", "swish", "转场"], "可补录/外采", None),
    ("crash_break", "爆裂/破碎", ["爆裂", "破碎", "破裂", "击碎", "碎裂", "爆破", "crash", "蛋壳破"], "可补录/外采", None),
    ("ambient_room", "室内环境底噪", ["环境音", "底噪", "室内环境", "空调", "电流", "ambient", "静场"], "待录", "S05_环境底噪"),
    ("ambient_outdoor", "户外环境音", ["虫鸣", "鸟叫", "街道", "车流", "雨声", "雷", "风雨"], "待录", "S05_环境底噪"),
]

BGM_FAMILY = ("bgm_change", "BGM 变化", "可补录/外采")
DUCK_FAMILY = ("ducking", "Ducking/静音闪避", "可补录/外采")


def match_family(entry):
    if entry.get("category_norm") == "背景音乐":
        return BGM_FAMILY[0]
    if entry.get("category_norm") == "音频闪避":
        return DUCK_FAMILY[0]
    text = " ".join(str(entry.get(k) or "") for k in ("sfx_name", "type", "description")).lower()
    for fid, _, kws, _, _ in FAMILIES:
        if any(k.lower() in text for k in kws):
            return fid
    return None


def extract_ducking_db(entry):
    m = re.search(r"衰减:\s*(-?\d+(?:\.\d+)?)dB", str(entry.get("description") or ""))
    return float(m.group(1)) if m else None


def main():
    parser = argparse.ArgumentParser(description="音效模式聚合器")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--top-examples", type=int, default=6)
    args = parser.parse_args()

    libdir = os.path.join(args.archive_dir, "_sfx_library")
    with open(os.path.join(libdir, "sfx_library_v2.json"), encoding="utf-8") as f:
        v2 = json.load(f)

    fam_meta = {fid: {"name": name, "supply_status": supply, "sound_lib_ref": ref}
                for fid, name, _, supply, ref in FAMILIES}
    fam_meta[BGM_FAMILY[0]] = {"name": BGM_FAMILY[1], "supply_status": BGM_FAMILY[2], "sound_lib_ref": None}
    fam_meta[DUCK_FAMILY[0]] = {"name": DUCK_FAMILY[1], "supply_status": DUCK_FAMILY[2], "sound_lib_ref": None}

    groups = defaultdict(list)
    for e in v2["entries"]:
        fid = match_family(e)
        if fid is None:
            fid = f"other_{e.get('category_norm') or '未分类'}"
        groups[fid].append(e)

    patterns = []
    for fid, entries in groups.items():
        meta = fam_meta.get(fid, {"name": f"其他·{fid.replace('other_', '')}",
                                  "supply_status": "待定", "sound_lib_ref": None})
        hist = [0] * 10
        for e in entries:
            pct = e.get("position_pct")
            if isinstance(pct, (int, float)):
                hist[min(int(pct // 10), 9)] += 1

        ducking_dbs = [d for d in (extract_ducking_db(e) for e in entries) if d is not None]
        # 代表用例：description 最丰富优先
        examples = sorted(entries, key=lambda e: -len(str(e.get("description") or "")))[:args.top_examples]

        patterns.append({
            "pattern_id": fid,
            "name": meta["name"],
            "freq": len(entries),
            "video_count": len({e["source_video"] for e in entries}),
            "account_count": len({e["source_account"] for e in entries}),
            "supply_status": meta["supply_status"],
            "sound_lib_ref": meta["sound_lib_ref"],
            "position_histogram": hist,
            "stage_dist": dict(Counter(e.get("narrative_stage") for e in entries if e.get("narrative_stage"))),
            "scene_dist": dict(Counter(e.get("scene") for e in entries if e.get("scene"))),
            "emotion_dist": dict(Counter(e.get("emotion_function") for e in entries if e.get("emotion_function"))),
            "coupling_dist": dict(Counter(e.get("coupling_type") for e in entries if e.get("coupling_type"))),
            "account_dist": dict(Counter(e["source_account"] for e in entries)),
            "typical_params": {"ducking_db_values": sorted(ducking_dbs)} if ducking_dbs else {},
            "examples": [{
                "sfx_id": e["sfx_id"], "video": e["source_video"], "account": e["source_account"],
                "timestamp_sec": e["timestamp_sec"], "name": e.get("sfx_name"),
                "description": str(e.get("description") or "")[:120],
                "stage": e.get("narrative_stage"), "emotion": e.get("emotion_function"),
            } for e in examples],
        })

    patterns.sort(key=lambda p: (-p["account_count"], -p["freq"]))
    # 每条明细的精确归属映射（供决策台 UI 精确过滤，避免前端重实现聚类口径）
    entry_map = {}
    for fid, entries in groups.items():
        for e in entries:
            entry_map[e["sfx_id"]] = fid
    out = {
        "version": "1.0",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_total_entries": v2["total_entries"],
        "total_patterns": len(patterns),
        "coverage_note": "全部条目 100% 归属（未命中语义家族的落 other_* 兜底模式）",
        "entry_map": entry_map,
        "patterns": patterns,
    }
    out_path = os.path.join(libdir, "sfx_patterns.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    covered = sum(p["freq"] for p in patterns)
    named = [p for p in patterns if not p["pattern_id"].startswith("other_")]
    print(f"✅ sfx_patterns.json: {len(patterns)} 个模式（语义家族 {len(named)} + 兜底 {len(patterns)-len(named)}）")
    print(f"   覆盖条目: {covered}/{v2['total_entries']}")
    print(f"   Top10: " + ", ".join(f"{p['name']}({p['freq']})" for p in patterns[:10]))
    if covered != v2["total_entries"]:
        print("❌ 覆盖数与源条目不一致")
        sys.exit(1)


if __name__ == "__main__":
    main()
