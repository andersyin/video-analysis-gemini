#!/usr/bin/env python3
"""Schema 验证 + 偷懒检测工具 —— 检查归档的分析 JSON 文件是否包含所有必填字段，
并自动检测大模型常见的偷懒行为（模板化、固定数量、自相矛盾）。

用法:
  # 验证某账号所有分析文件
  python validate_schema.py --archive-dir /path/to/archive --account "AccountD"

  # 只验证指定日期
  python validate_schema.py --archive-dir /path/to/archive --account "AccountD" --date 2026-07-24

  # 严格模式（空值/偷懒行为也算失败）
  python validate_schema.py --archive-dir /path/to/archive --account "AccountD" --strict

输出:
  - 逐文件检查结果（✅ 通过 / ❌ 缺失字段 / ⚠️ 空值 / 🦥 偷懒嫌疑）
  - 汇总报告（通过率、高频缺失字段统计、偷懒模式统计）
  - 退出码：全部通过 0，有缺失或偷懒 1
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# 各板块必填字段定义 —— 唯一事实源为 scripts/schema_contract.json。
# 改 prompts.json 字段后必须同步契约文件，并运行 --check-contract-sync 校验。
_CONTRACT_PATH = Path(__file__).resolve().parent / "schema_contract.json"

# 内嵌兜底（契约文件丢失时降级使用，并打印警告）
_FALLBACK_REQUIRED_FIELDS = {
    "cinematography": {
        "top": ["shot_timeline", "macro"],
        "macro": [
            "total_shots", "avg_shot_length_sec",
            "dominant_camera_height_range", "dominant_composition",
            "dominant_lighting", "dominant_color_temp",
            "visual_emotion_curve",
        ],
        "timeline_item_min_fields": ["index", "start_sec", "end_sec", "shot_type"],
    },
    "ai_fx": {
        "top": ["scene_timeline", "character_consistency", "generation_pipeline", "facial_animation"],
        "timeline_item_min_fields": ["start_sec", "end_sec", "technique"],
    },
    "audio": {
        "top": ["voiceover_transcript", "sfx_timeline", "bgm_timeline", "macro"],
        "macro": ["voiceover_ratio_pct", "bgm_genre", "audio_emotion_curve"],
    },
    "narrative": {
        "top": ["emotional_timeline", "story_beats", "script_full_text", "all_quotes", "macro"],
        "macro": ["attention_curve", "narrative_template", "story_structure"],
    },
    "sop": {
        "top": ["complexity_breakdown", "fixed_elements", "brand_elements", "production_complexity"],
    },
}


def load_contract():
    """加载 schema 契约。返回 (sections_dict, contract_meta)。文件缺失时降级内嵌版。"""
    if _CONTRACT_PATH.exists():
        try:
            raw = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
            return raw.get("sections", {}), {
                "version": raw.get("version", "?"),
                "source": str(_CONTRACT_PATH),
            }
        except json.JSONDecodeError as e:
            print(f"⚠️ schema_contract.json 解析失败（{e}），降级使用内嵌必填表")
    else:
        print(f"⚠️ 未找到 schema_contract.json（{_CONTRACT_PATH}），降级使用内嵌必填表")
    return _FALLBACK_REQUIRED_FIELDS, {"version": "embedded-fallback", "source": "embedded"}


REQUIRED_FIELDS, CONTRACT_META = load_contract()


def _load_honesty_tolerance():
    """从契约 density_gates 读取 honesty 观看时长容忍偏差（秒），兜底 1.0"""
    try:
        raw = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        return float(raw.get("density_gates", {}).get("honesty_view_duration_tolerance_sec", 1.0))
    except Exception:
        return 1.0


def check_contract_sync():
    """校验 prompts.json 声明字段与 schema_contract.json 是否对齐（防双重维护漂移）。

    检查两类键：
    1. 契约中 top/top_soft/macro/macro_soft/timeline_item_min_fields 的每个字段名，
       必须在 prompts.json 对应板块的 prompt 文本中出现；
    2. 契约中 prompt_must_mention 的关键字段同理（这些是消费端依赖但易被漏声明的字段）。
    """
    prompts_path = Path(__file__).resolve().parent / "prompts.json"
    if not prompts_path.exists():
        print(f"❌ prompts.json 不存在: {prompts_path}")
        return 1
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))

    problems = []
    for sec_name, spec in REQUIRED_FIELDS.items():
        sec_prompt = prompts.get(sec_name, {})
        prompt_text = sec_prompt.get("prompt", "") if isinstance(sec_prompt, dict) else ""
        if not prompt_text:
            problems.append(f"  ❌ prompts.json 缺板块 '{sec_name}' 或其 prompt 为空")
            continue
        keys = []
        for group in ("top", "top_soft", "macro", "macro_soft", "timeline_item_min_fields", "prompt_must_mention"):
            keys.extend(spec.get(group, []) or [])
        for key in sorted(set(keys)):
            if key not in prompt_text:
                problems.append(f"  ❌ {sec_name}: 契约字段 '{key}' 未在 prompts.json 中声明")

    # 反向轻查：契约版本号存在性
    if CONTRACT_META.get("version") in (None, "?", "embedded-fallback"):
        problems.append("  ⚠️ 契约文件缺 version 字段或正在使用内嵌兜底")

    print("=" * 60)
    print(f"契约同步校验 | 契约版本: {CONTRACT_META.get('version')} | 来源: {CONTRACT_META.get('source')}")
    print("=" * 60)
    if problems:
        print(f"🔴 {len(problems)} 处不同步：")
        for p in problems:
            print(p)
        print("\n修复：同步更新 prompts.json 或 schema_contract.json 后重跑本命令")
        return 1
    print("🟢 prompts.json 与 schema_contract.json 完全对齐")
    return 0


def validate_file(filepath):
    """验证单个分析 JSON 文件。返回 (passed, issues) 其中 issues 是字符串列表。"""
    issues = []

    try:
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, [f"JSON 解析失败: {e}"]
    except Exception as e:
        return False, [f"文件读取失败: {e}"]

    # ── 0. honesty_report 观看时长 vs _video_meta.json 真实时长比对（硬门禁，2026-07-26 新增）──
    # 依据：A/B 测试证明无事实校验闭环的直接 prompt 会产生 33% 时间轴幻觉；
    # honesty_report.view_duration_sec 必须与 ffprobe 元数据一致（±tolerance），防止诚实度报告本身造假。
    meta = data.get("_meta", {})
    hr = meta.get("honesty_report", {})
    if isinstance(hr, dict) and hr.get("view_duration_sec") is not None:
        video_meta_path = Path(filepath).parent / "_video_meta.json"
        if video_meta_path.exists():
            try:
                real_dur = float(json.loads(video_meta_path.read_text(encoding="utf-8")).get("duration_sec", 0))
                view_dur = float(hr["view_duration_sec"])
                tol = _load_honesty_tolerance()
                if real_dur > 0 and abs(view_dur - real_dur) > tol:
                    issues.append(
                        f"  ❌ _meta.honesty_report.view_duration_sec={view_dur} 与 "
                        f"_video_meta.json.duration_sec={real_dur} 偏差 >{tol}s——"
                        f"诚实度报告观看时长与真实时长不一致，疑似未完整观看"
                    )
            except (ValueError, TypeError, json.JSONDecodeError):
                pass


    # 兼容单板块和多板块格式
    if "sections" in meta:
        sections = meta["sections"]
    elif "section" in meta:
        sections = [meta["section"]]
    else:
        sections = list(REQUIRED_FIELDS.keys())

    for section_name in sections:
        if section_name not in REQUIRED_FIELDS:
            continue  # 自定义板块，跳过

        section_data = data.get(section_name)
        if section_data is None:
            issues.append(f"  ❌ 板块 '{section_name}' 完全缺失")
            continue

        if isinstance(section_data, dict) and "_raw" in section_data:
            issues.append(f"  ⚠️ 板块 '{section_name}' 仅有原始文本（JSON 解析失败，需手动检查）")
            continue

        req = REQUIRED_FIELDS[section_name]

        # 检查顶层字段（硬必填 → ❌；软必填 → ⚠️）
        for field in req.get("top", []):
            val = section_data.get(field) if isinstance(section_data, dict) else None
            if val is None:
                issues.append(f"  ❌ {section_name}.{field} 缺失")
            elif isinstance(val, list) and len(val) == 0:
                issues.append(f"  ⚠️ {section_name}.{field} 为空数组（可能正常，需确认）")
            elif isinstance(val, str) and val.strip() == "":
                issues.append(f"  ⚠️ {section_name}.{field} 为空字符串")

        for field in req.get("top_soft", []):
            val = section_data.get(field) if isinstance(section_data, dict) else None
            if val is None:
                issues.append(f"  ⚠️ {section_name}.{field} 缺失（契约软必填，建议补齐）")

        # 契约外键告警（2026-07-27 新增，非阻断）：消费端（脚本编辑器 / synthesis_engine 等）
        # 按契约字段消费，别名/漂移键（如 golden_quotes→all_quotes、reusable_assets→asset_reusability）
        # 会被静默丢弃或重复。先观测收敛不拦截；产出时请归一到契约字段名。
        if isinstance(section_data, dict):
            known = set(req.get("top", []) or []) | set(req.get("top_soft", []) or []) | {"macro"}
            extra = sorted(k for k in section_data if k not in known and not k.startswith("_"))
            if extra:
                issues.append(
                    f"  ⚠️ {section_name} 含契约外键 {extra}——"
                    f"消费端按契约白名单渲染，别名键请归一到契约字段"
                )

        # 检查 macro 子字段（硬/软两级）
        macro = section_data.get("macro", {}) if isinstance(section_data, dict) else {}
        for field in req.get("macro", []):
            val = macro.get(field)
            if val is None:
                issues.append(f"  ❌ {section_name}.macro.{field} 缺失")
            elif isinstance(val, str) and val.strip() == "":
                issues.append(f"  ⚠️ {section_name}.macro.{field} 为空")

        for field in req.get("macro_soft", []):
            val = macro.get(field)
            if val is None:
                issues.append(f"  ⚠️ {section_name}.macro.{field} 缺失（契约软必填，建议补齐）")

        # 检查 timeline 条目最小字段
        min_fields = req.get("timeline_item_min_fields", [])
        for tkey in ["shot_timeline", "scene_timeline", "emotional_timeline", "story_beats"]:
            timeline = section_data.get(tkey, []) if isinstance(section_data, dict) else []
            if not timeline or not isinstance(timeline, list):
                continue
            for i, item in enumerate(timeline):
                if not isinstance(item, dict):
                    issues.append(f"  ❌ {section_name}.{tkey}[{i}] 不是对象")
                    continue
                for mf in min_fields:
                    if mf not in item:
                        issues.append(f"  ❌ {section_name}.{tkey}[{i}].{mf} 缺失")

    # 偷懒检测
    issues.extend(detect_laziness(data))

    return len([i for i in issues if "❌" in i]) == 0, issues


def detect_laziness(data):
    """检测大模型偷懒行为——模板化、固定数量、自相矛盾。

    基于多轮实跑发现的 6 大偷懒模式，自动扫描分析 JSON。
    """
    issues = []

    def _get_duration(data):
        """从多个时间轴推断视频总时长"""
        # 优先从 shot_timeline 最后一条
        cine = data.get("cinematography", {})
        timeline = cine.get("shot_timeline", []) if isinstance(cine, dict) else []
        if timeline and isinstance(timeline, list) and timeline:
            last = timeline[-1]
            if isinstance(last, dict) and last.get("end_sec"):
                return float(last["end_sec"])
        # 其次从 voiceover_transcript 最后一条
        audio = data.get("audio", {})
        vo = audio.get("voiceover_transcript", []) if isinstance(audio, dict) else []
        if vo and isinstance(vo, list) and vo:
            last = vo[-1]
            if isinstance(last, dict) and last.get("end_sec"):
                return float(last["end_sec"])
        # 其次从 emotional_timeline
        narrative = data.get("narrative", {})
        emo = narrative.get("emotional_timeline", []) if isinstance(narrative, dict) else []
        if emo and isinstance(emo, list) and emo:
            last = emo[-1]
            if isinstance(last, dict) and last.get("end_sec"):
                return float(last["end_sec"])
        return 0.0

    duration = _get_duration(data)
    if duration == 0:
        issues.append("  🦥 无法从任何时间轴推断视频时长，可能全部时间轴为空")
    
    cine = data.get('cinematography', {})
    audio = data.get('audio', {})

    # ── 14. visual_content 软模板动作短语检测 ──
    SOFT_TEMPLATE_PHRASES = [
        "伸长脖子凑近镜头",
        "湿润鼻头特写",
        "眼睛直钩钩盯着侧面镜头",
        "耳朵微微前竖",
        "下巴紧贴地面仰视",
        "用两只前爪捂住面部后快速张开眼睛",
        "在茶几周围踱步转圈",
        "眼神瞟向零食袋",
        "跳上沙发挤在两人中间",
        "尾巴快速摆动",
        "前爪先着地缓冲",
        "背景呈暖色调灯光",
        "前爪搭上膝盖",
        "舌头伸出轻轻舔嘴唇",
        "歪着脑袋凝视前方，瞳孔微微放大",
        "急促地划过木地板，身体向前倾斜",
        "头定格不动，眼神直钩钩视向右侧",
    ]
    if isinstance(cine, dict):
        timeline_c = cine.get("shot_timeline", [])
        if isinstance(timeline_c, list) and timeline_c:
            soft_count = 0
            for item in timeline_c:
                if isinstance(item, dict):
                    vc = item.get("visual_content", "")
                    if any(p in vc for p in SOFT_TEMPLATE_PHRASES):
                        soft_count += 1
            if soft_count > 0:
                ratio = soft_count / len(timeline_c) * 100
                if ratio > 30:
                    issues.append(
                        f"  🦥 cinematography: visual_content含软模板短语 ({soft_count}/{len(timeline_c)}条, {ratio:.0f}%)，"
                        f"使用跨视频共享的动作描述，非该镜独特画面"
                    )

    # ── 15. visual_content "SubjectJ"前缀检测 ──
    if isinstance(cine, dict):
        timeline_v = cine.get("shot_timeline", [])
        if isinstance(timeline_v, list) and timeline_v:
            vector_count = 0
            for item in timeline_v:
                if isinstance(item, dict):
                    vc = item.get("visual_content", "")
                    if "SubjectJ" in vc:
                        vector_count += 1
            if vector_count > 0:
                ratio = vector_count / len(timeline_v) * 100
                if ratio > 50:
                    issues.append(
                        f"  🦥 cinematography: visual_content含'SubjectJ'前缀 ({vector_count}/{len(timeline_v)}条, {ratio:.0f}%)，"
                        f"'SubjectJ'不是有效视觉描述词"
                    )

    # ── 16. VO 视频名/ID 嵌入检测 ──
    vo_vid = audio.get("voiceover_transcript", [])
    if isinstance(vo_vid, list) and vo_vid:
        vo_ref_count = 0
        for item in vo_vid:
            if isinstance(item, dict):
                text = item.get("text", "")
                if (
                    re.search(r'TOP\d+', text)
                    or re.search(r'_[0-9]{2}', text)
                    or "POV" in text
                    or re.search(r'成精档案\s*\d{4}', text)
                    or re.search(r'关于.{2,10}现场', text)
                    or re.search(r'看.{2,15}这件事', text)
                ):
                    vo_ref_count += 1
        if vo_ref_count > 0:
            ratio = vo_ref_count / len(vo_vid) * 100
            if ratio > 30:
                issues.append(
                    f"  🦥 audio: VO文本含视频名/ID嵌入 ({vo_ref_count}/{len(vo_vid)}条, {ratio:.0f}%)，"
                    f"台词中引用了TOP编号/_01后缀/POV前缀/档案编号等"
                )

    # ── 1. VO 转录密度检查 ──
    audio = data.get("audio", {})
    if isinstance(audio, dict):
        vo = audio.get("voiceover_transcript", [])
        if isinstance(vo, list) and vo:
            vo_count = len(vo)
            expected_vo = max(3, int(duration / 10))
            if vo_count < expected_vo:
                issues.append(
                    f"  🦥 audio: VO转录仅{vo_count}条，{duration:.0f}秒视频预期≥{expected_vo}条 "
                    f"（每10秒≥1句）"
                )
            # 粗粒度检查：单条覆盖 >30秒
            for i, item in enumerate(vo):
                if isinstance(item, dict):
                    span = item.get("end_sec", 0) - item.get("start_sec", 0)
                    if span > 30:
                        issues.append(
                            f"  🦥 audio: VO第{i+1}条覆盖{span:.0f}秒（{item.get('start_sec', 0)}→{item.get('end_sec', 0)}），"
                            f"疑似粗粒度分段（单句应≤10秒）"
                        )
            # macro 自洽性
            macro = audio.get("macro", {})
            if isinstance(macro, dict):
                vo_ratio_declared = macro.get("voiceover_ratio_pct")
                if vo_ratio_declared is not None:
                    actual_ratio = round(
                        sum(
                            (item.get("end_sec", 0) - item.get("start_sec", 0))
                            for item in vo if isinstance(item, dict)
                        ) / duration * 100
                    )
                    if abs(actual_ratio - vo_ratio_declared) > 15:
                        issues.append(
                            f"  🦥 audio: macro.voiceover_ratio_pct={vo_ratio_declared}%，"
                            f"但transcript实际覆盖={actual_ratio}%，偏差>{15}%"
                        )

        # ── 2. SFX 数量检查 ──
        sfx = audio.get("sfx_timeline", [])
        if isinstance(sfx, list) and sfx:
            sfx_count = len(sfx)
            expected_sfx = max(3, int(duration / 10) * 2)
            if sfx_count < expected_sfx:
                issues.append(
                    f"  🦥 audio: SFX仅{sfx_count}条，{duration:.0f}秒视频预期≥{expected_sfx}条 "
                    f"（每10秒≥2个音效）"
                )
            # 固定3条检查（不论时长都是3条）
            if sfx_count == 3 and duration > 20:
                issues.append(
                    f"  🦥 audio: SFX恰好3条（{duration:.0f}秒视频），疑似模板化固定数量"
                )
            # ── 2b. SFX 三元耦合覆盖率检查（2026-07-26 新增，契约 density_gates 软要求 ≥50%）──
            triad_count = sum(
                1 for item in sfx
                if isinstance(item, dict) and item.get("triad_coupling")
            )
            triad_pct = triad_count / sfx_count * 100
            if triad_pct < 50:
                issues.append(
                    f"  🦥 audio: SFX 三元耦合覆盖率 {triad_pct:.0f}%（{triad_count}/{sfx_count} 条标注 "
                    f"triad_coupling），契约软要求 ≥50%——画面+SFX+Ducking 联动是音频结构化核心"
                )

        # ── 3. BGM 变化数量检查 ──
        bgm = audio.get("bgm_timeline", [])
        if isinstance(bgm, list) and bgm:
            bgm_count = len(bgm)
            if bgm_count == 3 and duration > 30:
                issues.append(
                    f"  🦥 audio: BGM变化恰好3条（{duration:.0f}秒视频），疑似模板化"
                )

    # ── 4. 情绪时间轴段数检查 ──
    narrative = data.get("narrative", {})
    if isinstance(narrative, dict):
        emo = narrative.get("emotional_timeline", [])
        if isinstance(emo, list) and emo:
            emo_count = len(emo)
            expected_emo = max(3, int(duration / 30))
            if emo_count < expected_emo:
                issues.append(
                    f"  🦥 narrative: 情绪时间轴仅{emo_count}段，{duration:.0f}秒视频预期≥{expected_emo}段 "
                    f"（每30秒≥1段）"
                )
            # 固定4段检查
            if emo_count == 4 and duration > 60:
                issues.append(
                    f"  🦥 narrative: 情绪时间轴恰好4段（{duration:.0f}秒视频），疑似模板化固定数量"
                )
            # 单段覆盖 >60秒
            for i, item in enumerate(emo):
                if isinstance(item, dict):
                    span = item.get("end_sec", 0) - item.get("start_sec", 0)
                    if span > 60:
                        issues.append(
                            f"  🦥 narrative: 情绪第{i+1}段覆盖{span:.0f}秒，"
                            f"过粗（单段应≤30秒）"
                        )

        # ── 5. climax/reversal 重叠检查 ──
        macro_n = narrative.get("macro", {})
        if isinstance(macro_n, dict):
            ac = macro_n.get("attention_curve", {})
            if isinstance(ac, dict):
                climax_sec = str(ac.get("climax_sec", ""))
                reversal_sec = str(ac.get("reversal_sec", ""))
                if climax_sec and reversal_sec and climax_sec == reversal_sec:
                    issues.append(
                        f"  🦥 narrative: climax_sec与reversal_sec完全相同（{climax_sec}），"
                        f"疑似偷懒复制"
                    )

        # ── 6. 金句模板文本检查 ──
        quotes = narrative.get("all_quotes", [])
        if isinstance(quotes, list) and quotes:
            template_markers = ["终极反转", "模板金句", "占位符", "的金句", "XX的"]
            for i, q in enumerate(quotes):
                if isinstance(q, dict):
                    text = q.get("text", "")
                    for marker in template_markers:
                        if marker in text:
                            issues.append(
                                f"  🦥 narrative: all_quotes[{i}].text含模板标记'{marker}'，"
                                f"疑似非原文（text='{text[:30]}...'）"
                            )
                            break

        # ── 7. narrative_template 固定时间区间检查 ──
        ntemplate = macro_n.get("narrative_template", "") if isinstance(macro_n, dict) else ""
        fixed_patterns = ["0-3s", "0-3秒", "3-15s", "3-15秒", "15-25s", "15-25秒"]
        for pat in fixed_patterns:
            if pat in ntemplate:
                issues.append(
                    f"  🦥 narrative: narrative_template含固定时间区间'{pat}'，"
                    f"未根据视频实际时长（{duration:.0f}秒）调整"
                )
                break

    # ── 8. cinematography 自洽性检查 ──
    cine = data.get("cinematography", {})
    if isinstance(cine, dict):
        timeline = cine.get("shot_timeline", [])
        if isinstance(timeline, list) and timeline:
            # 8a. visual_content 模板化检查
            import re as _re
            vc_template = 0
            for item in timeline:
                if isinstance(item, dict):
                    vc = item.get("visual_content", "")
                    if _re.match(r'第\s*\d+\s*[镜镜]', vc) or "镜头展现" in vc or "镜展现" in vc:
                        vc_template += 1
            if vc_template > 0:
                ratio = vc_template / len(timeline) * 100
                if ratio > 50:
                    issues.append(
                        f"  🦥 cinematography: visual_content模板化 ({vc_template}/{len(timeline)}条, {ratio:.0f}%)，"
                        f"含「第N镜」「镜头展现」模板，非实际画面描述"
                    )
        macro_c = cine.get("macro", {})
        if isinstance(timeline, list) and timeline and isinstance(macro_c, dict):
            actual_shots = len(timeline)
            declared_shots = macro_c.get("total_shots", 0)
            if declared_shots != actual_shots:
                issues.append(
                    f"  🦥 cinematography: macro.total_shots={declared_shots}，"
                    f"但shot_timeline实际{actual_shots}条，不一致"
                )

            if actual_shots > 0:
                # duration_sec 缺失时回退用 end_sec-start_sec（2026-07-26 验收发现：
                # Flash 产出常不含 duration_sec，旧口径 sum=0 会误报不一致）
                def _shot_dur(item):
                    if not isinstance(item, dict):
                        return 0
                    d = item.get("duration_sec")
                    if isinstance(d, (int, float)) and d > 0:
                        return d
                    return item.get("end_sec", 0) - item.get("start_sec", 0)

                total_dur = sum(_shot_dur(item) for item in timeline)
                declared_avg = macro_c.get("avg_shot_length_sec", 0)
                actual_avg = round(total_dur / actual_shots, 1)
                if declared_avg > 0 and abs(declared_avg - actual_avg) > 0.5:
                    issues.append(
                        f"  🦥 cinematography: macro.avg_shot_length={declared_avg}，"
                        f"但实际计算={actual_avg}（sum/len），不一致"
                    )

                # 最后一条 end_sec ≈ duration
                last_end = timeline[-1].get("end_sec", 0) if isinstance(timeline[-1], dict) else 0
                if abs(last_end - duration) > 2:
                    issues.append(
                        f"  🦥 cinematography: shot_timeline最后end_sec={last_end}，"
                        f"但视频时长≈{duration:.0f}，偏差>2秒"
                    )

    # ── 8b. ai_fx generation_evidence 帧级证据检查（2026-07-26 新增）──
    # 依据：A/B 测试中两路径对"是否有 AI 生成痕迹"给出相反结论——判定必须挂帧级证据
    ai_fx_sec = data.get("ai_fx", {})
    if isinstance(ai_fx_sec, dict):
        gen_ev = ai_fx_sec.get("generation_evidence")
        if gen_ev is not None:
            if not isinstance(gen_ev, list) or len(gen_ev) < 3:
                n = len(gen_ev) if isinstance(gen_ev, list) else 0
                issues.append(
                    f"  🦥 ai_fx: generation_evidence 仅 {n} 条，契约要求 ≥3 条帧级证据——"
                    f"AI 生成判定不能只给结论不给证据"
                )
            elif duration > 0:
                for i, ev in enumerate(gen_ev):
                    if isinstance(ev, dict):
                        sec_val = ev.get("sec")
                        if isinstance(sec_val, (int, float)) and sec_val > duration:
                            issues.append(
                                f"  🦥 ai_fx: generation_evidence[{i}].sec={sec_val} 超出视频时长 "
                                f"{duration:.0f}s，疑似幻觉证据"
                            )

    # ── 9. SOP macro 空检查 ──
    sop = data.get("sop", {})
    if isinstance(sop, dict):
        pc = sop.get("production_complexity", {})
        if not pc or (isinstance(pc, dict) and not any(pc.values())):
            issues.append("  🦥 sop: production_complexity 为空对象，疑似未填写")
        ar = sop.get("asset_reusability", {})
        if not ar or (isinstance(ar, dict) and not any(ar.values())):
            issues.append("  🦥 sop: asset_reusability 为空对象，疑似未填写")
        monet = sop.get("monetization", {})
        if not monet or (isinstance(monet, dict) and not any(monet.values())):
            issues.append("  🦥 sop: monetization 为空对象，疑似未填写")

    # ── 10. VO 文本模板化检查 ──
    if isinstance(audio, dict):
        vo = audio.get("voiceover_transcript", [])
        if isinstance(vo, list) and vo:
            vo_template_count = 0
            vo_templates = ["【开场第", "【第", "大家好，今天给大家带来",
                             "第2段剧情具体讲述", "第3段剧情具体讲述",
                             "剧情具体讲述"]
            for item in vo:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    for pat in vo_templates:
                        if pat in text:
                            vo_template_count += 1
                            break
            if vo_template_count > 0:
                ratio = vo_template_count / len(vo) * 100
                if ratio > 50:
                    issues.append(
                        f"  🦥 audio: VO文本模板化严重 ({vo_template_count}/{len(vo)}条, {ratio:.0f}%)，"
                        f"含「【开场第N句」「大家好，今天给大家带来」「剧情具体讲述」等模板，"
                        f"非视频实际台词原文"
                    )

        # ── 11. SFX 描述模板化检查 ──
        sfx = audio.get("sfx_timeline", [])
        if isinstance(sfx, list) and sfx:
            sfx_template_count = 0
            sfx_templates = ["动态切帧/动作关键点施加", "动态切帧", "动作关键点施加"]
            for item in sfx:
                if isinstance(item, dict):
                    desc = item.get("description", "")
                    for pat in sfx_templates:
                        if pat in desc:
                            sfx_template_count += 1
                            break
            if sfx_template_count > 0:
                ratio = sfx_template_count / len(sfx) * 100
                if ratio > 50:
                    issues.append(
                        f"  🦥 audio: SFX描述模板化 ({sfx_template_count}/{len(sfx)}条, {ratio:.0f}%)，"
                        f"含「动态切帧/动作关键点施加」模板，非实际音效描述"
                    )

        # ── 12. BGM 描述模板化检查 ──
        bgm = audio.get("bgm_timeline", [])
        if isinstance(bgm, list) and bgm:
            bgm_template_count = 0
            for item in bgm:
                if isinstance(item, dict):
                    desc = item.get("description", "")
                    if desc.strip() in ["", "BGM"] or (desc.endswith("BGM") and len(desc) < 30):
                        bgm_template_count += 1
            if bgm_template_count > 0:
                ratio = bgm_template_count / len(bgm) * 100
                if ratio > 50:
                    issues.append(
                        f"  🦥 audio: BGM描述模板化 ({bgm_template_count}/{len(bgm)}条, {ratio:.0f}%)，"
                        f"描述过短或仅为「BGM」，非实际BGM变化描述"
                    )

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="分析 JSON 文件 schema 验证（必填字段检查）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--archive-dir", help="归档根目录")
    parser.add_argument("--account", help="账号名")
    parser.add_argument("--date", help="只验证指定日期的文件（可选）")
    parser.add_argument("--strict", action="store_true", help="严格模式：空数组/空字符串也算失败")
    parser.add_argument("--check-contract-sync", action="store_true",
                        help="校验 prompts.json 与 schema_contract.json 是否对齐（改提示词后必跑）")
    args = parser.parse_args()

    if args.check_contract_sync:
        sys.exit(check_contract_sync())

    if not args.archive_dir or not args.account:
        parser.error("验证分析文件时必须提供 --archive-dir 与 --account")

    videos_dir = Path(args.archive_dir) / args.account / "videos"
    if not videos_dir.exists():
        sys.exit(f"错误：账号目录不存在: {videos_dir}")

    all_files = sorted(videos_dir.glob("*/analysis_*.json"))
    if args.date:
        all_files = [f for f in all_files if f.name == f"analysis_{args.date}.json"]

    if not all_files:
        sys.exit("未找到分析文件。")

    total = len(all_files)
    passed = 0
    warn_only = 0
    lazy_count = 0
    failed = 0
    all_issues = []

    for filepath in all_files:
        ok, issues = validate_file(filepath)
        rel_path = filepath.relative_to(videos_dir)

        has_errors = any("❌" in i for i in issues)
        has_warnings = any("⚠️" in i for i in issues)
        has_lazy = any("🦥" in i for i in issues)

        if args.strict:
            ok = len(issues) == 0

        if ok and not issues:
            passed += 1
            print(f"✅ {rel_path}")
        elif ok and has_warnings and not has_lazy:
            warn_only += 1
            print(f"⚠️ {rel_path}")
            for issue in issues:
                print(f"   {issue}")
        elif ok and has_lazy:
            lazy_count += 1
            print(f"🦥 {rel_path}")
            for issue in issues:
                print(f"   {issue}")
        else:
            failed += 1
            print(f"❌ {rel_path}")
            for issue in issues:
                print(f"   {issue}")

        all_issues.extend([(str(rel_path), issue) for issue in issues])

    # 汇总
    print(f"\n{'='*60}")
    print(f"总计: {total} | ✅ 通过: {passed} | ⚠️ 仅警告: {warn_only} | 🦥 偷懒嫌疑: {lazy_count} | ❌ 有缺失: {failed}")

    # 偷懒模式统计
    lazy_patterns = Counter()
    for _, issue in all_issues:
        if "🦥" in issue:
            # 提取板块名
            parts = issue.strip().split(":")
            if len(parts) >= 2:
                lazy_patterns[parts[0].strip().replace("🦥", "").strip()] += 1
    if lazy_patterns:
        print("\n🦥 偷懒模式统计:")
        for pattern, count in lazy_patterns.most_common(10):
            print(f"  {pattern}: {count} 次")

    # 高频缺失字段统计
    if all_issues:
        field_counts = Counter()
        for _, issue in all_issues:
            parts = issue.strip().split()
            for p in parts:
                if "." in p and not p.startswith("❌") and not p.startswith("⚠️") and not p.startswith("🦥"):
                    field_counts[p] += 1

        if field_counts:
            print("\n高频缺失字段 Top 10:")
            for field, count in field_counts.most_common(10):
                print(f"  {field}: {count} 次")

    sys.exit(0 if failed == 0 and lazy_count == 0 else 1)


if __name__ == "__main__":
    main()
