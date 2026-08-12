#!/usr/bin/env python3
"""
音效库 v2 富化器 — 确定性规则为主、LLM 补丁为辅的四维打标

从 sfx_library.json + video_catalog.json 产出 sfx_library_v2.json，每条新增：
  - category_norm: 类别归一（33 种拼写 → 8 类词表）
  - scene: 场景（客厅/沙发·卧室·门口/玄关·厨房/餐食·浴室·户外·车内·画外/虚拟）
  - emotion_function: 情绪功能（钩子引入·推进铺垫·悬念紧张·反转爆点·喜剧滑稽·温情共鸣·收尾回落）
  - coupling_type: 声画耦合（动作卡点·声音先行·画面先行·纯氛围铺底·转场衔接；不适用为空）
  - narrative_stage: 叙事阶段（开头钩子·铺垫推进·转折高潮·收尾）——优先真实 story_beats 对齐，无节拍回退百分位
  - position_pct: 时间进度百分位（0-100）

设计原则（对齐 KB 零 LLM 确定性自动化实践）：
  规则可复现、可重跑；规则覆盖不了的条目落 v2_unmatched.json 清单，
  由 LLM 会话人工判读后写入 v2_patch.json（{sfx_id: {field: value}}），
  本脚本 --patch 应用补丁（补丁优先级最高）。重跑幂等。

用法:
  python3 sfx_enrich.py --archive-dir /path/to/对标视频分析资产
  python3 sfx_enrich.py --archive-dir ... --patch  # 应用 _sfx_library/v2_patch.json
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

SCENE_VOCAB = ["客厅/沙发", "卧室", "门口/玄关", "厨房/餐食", "浴室", "户外", "车内", "画外/虚拟"]
EMOTION_VOCAB = ["钩子引入", "推进铺垫", "悬念紧张", "反转爆点", "喜剧滑稽", "温情共鸣", "收尾回落"]
COUPLING_VOCAB = ["动作卡点", "声音先行", "画面先行", "纯氛围铺底", "转场衔接"]
STAGE_VOCAB = ["开头钩子", "铺垫推进", "转折高潮", "收尾"]
CATEGORY_VOCAB = ["动作音效/Foley", "戏剧性SFX", "环境音", "背景音乐", "音频闪避", "UI/游戏音效", "转场音效", "角色发声"]

# ---- 类别归一（2026-07-31 全库 33 种实测拼写） ----
CATEGORY_MAP = {
    "动作音效": "动作音效/Foley", "foley": "动作音效/Foley", "pet foley": "动作音效/Foley",
    "拟音sfx": "动作音效/Foley", "道具音效": "动作音效/Foley", "生活音效": "动作音效/Foley",
    "打击音效": "动作音效/Foley", "汽车音效": "动作音效/Foley", "环境/动作音效": "动作音效/Foley",
    "环境与动作音效": "环境音", "动作音效/生物拟音": "角色发声",
    "戏剧性sfx": "戏剧性SFX", "humor fx": "戏剧性SFX", "magic fx": "戏剧性SFX",
    "搞笑动漫音效": "戏剧性SFX", "搞笑音效": "戏剧性SFX", "cartoon": "戏剧性SFX",
    "环境音": "环境音", "环境/拟音": "环境音", "环境音效": "环境音", "环境音/拟音": "环境音",
    "环境拟音": "环境音", "自然音效": "环境音",
    "背景音乐": "背景音乐", "环境音/bgm余音": "背景音乐",
    "音频闪避": "音频闪避",
    "ui": "UI/游戏音效", "ui音效": "UI/游戏音效", "ui/动作音效": "UI/游戏音效",
    "game sfx": "UI/游戏音效", "车机音效": "UI/游戏音效",
    "转场音效": "转场音效",
}

BEAT_TO_STAGE = {"hook": "开头钩子", "setup": "铺垫推进", "rising": "铺垫推进",
                 "climax": "转折高潮", "reversal": "转折高潮", "ending": "收尾"}


def kw(text, *words):
    return any(w in text for w in words)


def norm_category(entry, text):
    raw = str(entry.get("category") or "").strip().lower()
    if raw in CATEGORY_MAP:
        return CATEGORY_MAP[raw]
    # 空类别推断
    etype = str(entry.get("type") or "").strip().lower()
    if etype == "bgm变化" or str(entry.get("sfx_name", "")).startswith("BGM_"):
        return "背景音乐"
    if etype == "ducking/静音":
        return "音频闪避"
    if kw(text, "喵", "汪", "吠", "哼唧", "呜咽", "嗷", "叫声", "犬吠", "猫叫", "狗叫", "呼噜", "喘"):
        return "角色发声"
    if kw(text, "转场", "whoosh", "swish", "过渡"):
        return "转场音效"
    if etype in ("foley", "拟音"):
        return "动作音效/Foley"
    if etype in ("synthesized", "合成"):
        return "戏剧性SFX"
    if etype in ("ambient", "环境"):
        return "环境音"
    # 末级兼容：type 空但名称/描述语义明确（2026-07-31：铁头阿彪 131 条 type 空 + kat 英文条目）
    lower = text.lower()
    if kw(text, "提示音", "语音", "按键", "触屏", "POS", "App", "车机", "机械合成", "电子音"):
        return "UI/游戏音效"
    if kw(text, "动漫", "卡通", "感叹号", "闪光", "震惊", "夸张", "漫画", "轰鸣", "变身", "特效") \
            or kw(lower, "comic", "shock", "dramatic", "sting", "whoosh"):
        return "戏剧性SFX"
    if kw(text, "声", "响", "音", "唷", "咕", "噡", "咓", "唔") \
            or kw(lower, "click", "clink", "slam", "creak", "pop", "tick", "thud", "crash",
                  "rattle", "rustle", "tap", "knock", "squeak", "splash", "bubble", "chain",
                  "key", "door", "static", "heel"):
        return "动作音效/Foley"
    return None


def infer_scene(text, category_norm):
    if category_norm in ("背景音乐", "音频闪避", "转场音效", "UI/游戏音效"):
        return "画外/虚拟"
    if kw(text, "沙发", "客厅", "电视", "茶几", "地毯", "抱枕"):
        return "客厅/沙发"
    if kw(text, "床", "卧室", "被子", "被窝", "枕", "睡"):
        return "卧室"
    if kw(text, "门口", "玄关", "门铃", "敲门", "关门", "开门", "门把", "推门"):
        return "门口/玄关"
    if kw(text, "厨房", "碗", "食盆", "餐", "零食", "爆米花", "喂食", "咀嚼", "进食", "吃", "锅", "冰箱"):
        return "厨房/餐食"
    if kw(text, "浴", "洗澡", "吹风机", "水龙头", "淋浴"):
        return "浴室"
    if kw(text, "户外", "街", "草地", "马路", "车流", "室外", "风声", "虫鸣", "雨", "雷",
          "雪", "沙石", "花园", "浇水", "花瓣", "花茂", "桥洞", "公路", "路面", "庭院"):
        return "户外"
    if kw(text, "车内", "车厢", "方向盘", "刹车", "安全带", "引擎", "车门", "驾驶",
          "车库", "轮胎", "胎噪", "泊车", "悬挂", "底盘", "倒车", "车身", "车座", "座椅背"):
        return "车内"
    if kw(text, "画外", "旁白", "字幕", "音效包", "卡通", "动漫", "游戏", "合成"):
        return "画外/虚拟"
    return None


def infer_emotion(text, stage):
    if kw(text, "搞笑", "滑稽", "喜剧", "爆笑", "逗", "荒诞", "卡通", "动漫", "俏皮", "诙谐", "幽默"):
        return "喜剧滑稽"
    if kw(text, "悬念", "紧张", "惊悚", "危机", "警报", "心跳", "凝视", "压迫", "不安", "阴森"):
        return "悬念紧张"
    if kw(text, "反转", "爆点", "怒吼", "爆音", "冲击", "震惊", "打击", "轰", "炸"):
        return "反转爆点"
    if kw(text, "温馨", "治愈", "温情", "依偎", "安抚", "舒缓", "温柔", "浪漫", "感人", "共鸣"):
        return "温情共鸣"
    # 回退：按叙事阶段的默认情绪职能
    return {"开头钩子": "钩子引入", "铺垫推进": "推进铺垫",
            "转折高潮": "反转爆点", "收尾": "收尾回落"}.get(stage)


def infer_coupling(entry, text, category_norm):
    if category_norm == "音频闪避":
        return ""  # 混音技法，声画耦合维度不适用
    if category_norm == "转场音效" or kw(text, "转场", "whoosh", "过渡"):
        return "转场衔接"
    if category_norm in ("背景音乐", "环境音"):
        return "纯氛围铺底"
    sync = str(entry.get("sync_with_visual") or "")
    if kw(sync + text, "卡点", "同步", "命中") or sync == "true" \
            or kw(sync.lower(), "coupled", "sync"):
        return "动作卡点"
    if kw(text, "预示", "先行", "预告", "渐入", "先响"):
        return "声音先行"
    if kw(text, "延迟", "揭示", "画面先"):
        return "画面先行"
    if category_norm == "角色发声":
        # 持续性生理音铺底 vs 瞬时发声卡点
        if kw(text, "呼噜", "打呼", "喘", "呼吸", "低鸣"):
            return "纯氛围铺底"
        return "动作卡点"
    if category_norm == "动作音效/Foley":
        # Foley 专业定义即与画面动作同步的拟音，默认动作卡点
        return "动作卡点"
    if category_norm in ("戏剧性SFX", "UI/游戏音效") and kw(text, "声", "音", "响"):
        return "动作卡点"
    return None


def infer_stage(ts, duration, beats):
    # 优先真实叙事节拍区间
    for b in beats or []:
        end = b.get("end_sec")
        if b["start_sec"] <= ts and (end is None or ts < end + 0.001):
            candidate = BEAT_TO_STAGE.get(b["beat"])
            if candidate:
                return candidate
    # 回退百分位
    if duration and duration > 0:
        pct = ts / duration * 100
        if pct < 15:
            return "开头钩子"
        if pct < 50:
            return "铺垫推进"
        if pct < 85:
            return "转折高潮"
        return "收尾"
    return None


def load_shot_context(archive_dir, catalog):
    """从各视频 analysis JSON 的 cinematography.shot_timeline 构建 {video_id: [(start,end,visual_content)]}，
    供场景推断用镜头画面描述做上下文增强（纯确定性，不靠 LLM）"""
    from pathlib import Path
    shots = {}
    for json_path in Path(archive_dir).glob("*/videos/*/analysis_*.json"):
        vid = json_path.parent.name
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            tl = data.get("cinematography", {}).get("shot_timeline", []) or []
        except Exception:
            continue
        lst = []
        for s in tl:
            if not isinstance(s, dict):
                continue
            try:
                start = float(str(s.get("start_sec", 0)).split("-")[0])
                end = float(str(s.get("end_sec", start)).split("-")[0])
            except (TypeError, ValueError):
                continue
            lst.append((start, end, str(s.get("visual_content") or "")))
        shots[vid] = lst
    return shots


def shot_text_at(shots, video_id, ts, window=1.0):
    """取 sfx 时间戳所在镜头（±window 容差）的画面描述文本"""
    parts = []
    for start, end, vc in shots.get(video_id, []):
        if start - window <= ts <= end + window:
            parts.append(vc)
    return " ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="音效库 v2 富化器")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--patch", action="store_true", help="应用 _sfx_library/v2_patch.json 补丁")
    args = parser.parse_args()

    libdir = os.path.join(args.archive_dir, "_sfx_library")
    with open(os.path.join(libdir, "sfx_library.json"), encoding="utf-8") as f:
        lib = json.load(f)
    with open(os.path.join(libdir, "video_catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    vmap = {v["video_id"]: v for v in catalog["videos"]}

    patch = {}
    patch_path = os.path.join(libdir, "v2_patch.json")
    if args.patch and os.path.exists(patch_path):
        with open(patch_path, encoding="utf-8") as f:
            patch = json.load(f)

    entries_v2, unmatched = [], []
    shots = load_shot_context(args.archive_dir, catalog)
    for e in lib["entries"]:
        v = dict(e)
        text = " ".join(str(e.get(k) or "") for k in ("sfx_name", "type", "description", "sync_with_visual"))
        vid = vmap.get(e.get("source_video"), {})
        duration = vid.get("duration_sec")
        ts = float(e.get("timestamp_sec", 0))
        # 镜头画面上下文：仅用于场景推断（情绪/耦合维度用画面文本易误判，不入）
        scene_text = text + " " + shot_text_at(shots, e.get("source_video", ""), ts)

        cat = norm_category(e, text)
        stage = infer_stage(ts, duration, vid.get("beats"))
        v["category_norm"] = cat
        v["scene"] = infer_scene(scene_text, cat) if cat else infer_scene(scene_text, "")
        v["emotion_function"] = infer_emotion(text, stage)
        v["coupling_type"] = infer_coupling(e, text, cat or "")
        v["narrative_stage"] = stage
        v["position_pct"] = round(ts / duration * 100, 1) if duration else None

        # 补丁覆盖（LLM 人工判读结果，优先级最高）
        for k, val in patch.get(e["sfx_id"], {}).items():
            v[k] = val

        missing = [k for k in ("category_norm", "scene", "emotion_function", "narrative_stage") if not v.get(k)]
        if v.get("coupling_type") is None:
            missing.append("coupling_type")
        if missing:
            unmatched.append({"sfx_id": e["sfx_id"], "missing": missing,
                              "sfx_name": e.get("sfx_name"), "type": e.get("type"),
                              "description": str(e.get("description"))[:80]})
        entries_v2.append(v)

    # 词表合法性校验（防补丁写出词表外值）
    vocab_errors = []
    for v in entries_v2:
        for field, vocab in (("category_norm", CATEGORY_VOCAB), ("scene", SCENE_VOCAB),
                             ("emotion_function", EMOTION_VOCAB), ("narrative_stage", STAGE_VOCAB)):
            if v.get(field) and v[field] not in vocab:
                vocab_errors.append(f"{v['sfx_id']}.{field}={v[field]}")
        if v.get("coupling_type") and v["coupling_type"] not in COUPLING_VOCAB:
            vocab_errors.append(f"{v['sfx_id']}.coupling_type={v['coupling_type']}")
    if vocab_errors:
        print("❌ 词表外值:", vocab_errors[:10])
        sys.exit(1)

    out = {
        "version": "2.0",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_version": lib.get("last_updated"),
        "vocab": {"category_norm": CATEGORY_VOCAB, "scene": SCENE_VOCAB,
                  "emotion_function": EMOTION_VOCAB, "coupling_type": COUPLING_VOCAB,
                  "narrative_stage": STAGE_VOCAB},
        "total_entries": len(entries_v2),
        "entries": entries_v2,
    }
    with open(os.path.join(libdir, "sfx_library_v2.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(os.path.join(libdir, "v2_unmatched.json"), "w", encoding="utf-8") as f:
        json.dump({"count": len(unmatched), "items": unmatched}, f, ensure_ascii=False, indent=2)

    n = len(entries_v2)
    print(f"✅ sfx_library_v2.json: {n} 条")
    for field in ("category_norm", "scene", "emotion_function", "coupling_type", "narrative_stage"):
        filled = sum(1 for v in entries_v2 if v.get(field) or v.get(field) == "")
        real = sum(1 for v in entries_v2 if v.get(field))
        print(f"   {field}: 有值 {real} ({real*100//n}%)  含'不适用空值' {filled}")
    print(f"   待 LLM 补丁: {len(unmatched)} 条 → v2_unmatched.json")
    if patch:
        print(f"   已应用补丁: {len(patch)} 条")


if __name__ == "__main__":
    main()
