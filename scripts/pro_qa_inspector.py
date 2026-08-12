#!/usr/bin/env python3
"""
Layer 3 质检器 — Pro 3.1 深度质检与对抗探针模块（两阶段模式）

架构（2026-07-25 重造）：
  阶段A（本脚本）：物理级硬门禁 + 规则预检 + 组装 Pro 审查包
    python3 pro_qa_inspector.py --archive-dir <dir> --account <acct> --video-id <vid> --date <date>
    → 产出 _pro_review_packet.json，状态置为 PRO_AUDITING

  阶段B（Agent + Pro 3.1）：Agent 将审查包交给 Pro 3.1 完成语义级审查：
    1. Pro 独立 view_file 观看视频，抽查 honesty_report 中每板块 ≥1 条
       specific_details / evidence 是否属实（诚实度终审的唯一可信路径）
    2. 语义级审查：声画脱节 / 因果矛盾 / 偷懒模板
    3. 结合 Whisper STT Ground Truth 校验 VO 转录覆盖
    Pro 产出 _pro_review_result.json 后回收：
    python3 pro_qa_inspector.py --ingest-pro-result --archive-dir <dir> --account <acct> --video-id <vid>
    → Score >= 90 进入 Layer 4；否则用 Pro 探针驱动定点修补，3 轮熔断

  --rule-only：仅用规则评分（快速预检用，不得作为交付依据）

Pro 结果 schema（_pro_review_result.json）：
  {
    "score": 0-100,
    "verdict": "pass" | "fail",
    "spot_check": {"details_sampled": 3, "details_verified": 2, "mismatches": ["..."]},
    "semantic_issues": ["..."],
    "target_probes": [{"section": "audio", "target_sec": "03.20-05.00", "question": "..."}]
  }

  # 查看审查结果
  python3 pro_qa_inspector.py --show-result \
    --archive-dir /path/to/archive --account "AccountD" --video-id "TOP01_xxxx"
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


# ── 二维审查卡片定义（规则预检用；语义终审由 Pro 3.1 完成）──
QA_DIMENSIONS = {
    "honesty": {
        "name": "诚实度与证据链真实性",
        "weight": 50,
        "checks": [
            "honesty_report.script_generated 是否为 false",
            "honesty_report.view_file_called / watched_full_video 是否为 true",
            "sections.<板块>.evidence 是否包含精确时间点 + 具体画面/声音",
            "sections.<板块>.evidence 是否为泛化描述（如'有一只狗在动'）——泛化则扣分",
            "sections.<板块>.specific_details_only_from_watching 是否列出 3-5 个只有看过视频才知道的细节",
            "fields_not_from_viewing 是否诚实标注了无法提取的字段",
        ],
    },
    "audio_visual_logic": {
        "name": "声画及叙事逻辑自洽性",
        "weight": 50,
        "checks": [
            "VO 转录文本 vs script_full_text 是否匹配",
            "SFX 时间戳是否落在对应镜头区间内",
            "BGM 变化时间点 vs 情绪曲线转折点是否对齐（±1s）",
            "Ducking 事件 vs SFX 事件是否对齐（±1s）",
            "micro_detail vs visual_content 是否矛盾",
            "macro.total_shots == len(shot_timeline)",
            "shot_timeline 最后一条 end_sec ≈ 视频总时长（±1s）",
            "narrative climax_sec 和 reversal_sec 不相同",
            "情绪曲线覆盖全片（无时间轴断档）",
        ],
    },
}

def _load_sections():
    """从 schema_contract.json 读取板块列表（唯一事实源），失败时降级内嵌"""
    contract_path = Path(__file__).resolve().parent / "schema_contract.json"
    if contract_path.exists():
        try:
            raw = json.loads(contract_path.read_text(encoding="utf-8"))
            secs = list(raw.get("sections", {}).keys())
            if secs:
                return secs
        except json.JSONDecodeError:
            pass
    return ["cinematography", "ai_fx", "audio", "narrative", "sop"]


def _load_section_top_fields():
    """从 schema_contract.json 读取各板块 top 必填字段（硬门禁用）。

    历史漏洞（2026-07-26 验收发现）：硬门禁此前只查板块存在性，不查板块内
    top 必填字段，导致 narrative.emotional_timeline 缺失仍一路 PASS_DELIVERED。
    """
    contract_path = Path(__file__).resolve().parent / "schema_contract.json"
    if contract_path.exists():
        try:
            raw = json.loads(contract_path.read_text(encoding="utf-8"))
            return {
                sec: spec.get("top", [])
                for sec, spec in raw.get("sections", {}).items()
                if isinstance(spec, dict)
            }
        except json.JSONDecodeError:
            pass
    return {}


SECTIONS = _load_sections()
SECTION_TOP_FIELDS = _load_section_top_fields()
PASS_THRESHOLD = 90
MAX_RETRIES = 3

# Layer 3 入口合法状态集（风险1修复：PROBE_REPAIRING 修补后必须能重新进 L3）
L3_ENTRY_STATES = {"FLASH_EXTRACTED", "PROBE_REPAIRING", "PRO_AUDITING"}


def file_md5(path):
    """计算文件 md5（用于感知 analysis 是否在组包之间被修补）"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def append_state(state_path, new_state, extra=None, dedup=True):
    """追加状态记录。dedup=True 时若 current_state 已是目标状态则不重复追加（幂等）"""
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
    changed = state.get("current_state") != new_state
    state["current_state"] = new_state
    if changed or not dedup:
        entry = {"state": new_state, "timestamp": datetime.now().isoformat()}
        if extra:
            entry.update(extra)
        state.setdefault("history", []).append(entry)
    elif extra:
        # 状态未变但有附加信息（如 sop_path），只更新顶层字段
        state.update({k: v for k, v in extra.items()})
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return state


def count_repairs(state):
    """熔断计数 = history 中 PROBE_REPAIRING 次数"""
    return len([h for h in state.get("history", []) if h.get("state") == "PROBE_REPAIRING"])


def load_analysis_json(archive_dir, account, video_id, date):
    """加载 Flash 产出的分析 JSON"""
    json_path = os.path.join(archive_dir, account, "videos", video_id, f"analysis_{date}.json")
    if not os.path.exists(json_path):
        print(f"❌ 分析文件不存在: {json_path}")
        return None, None
    with open(json_path) as f:
        return json.load(f), json_path


def find_latest_analysis(archive_dir, account, video_id):
    """ingest 阶段未传 --date 时，自动找最新日期的 analysis 文件"""
    video_dir = Path(archive_dir) / account / "videos" / video_id
    candidates = sorted(video_dir.glob("analysis_*.json"), reverse=True)
    if not candidates:
        return None, None, None
    latest = candidates[0]
    date = latest.stem.replace("analysis_", "")
    with open(latest) as f:
        return json.load(f), str(latest), date


def load_grounding_payload(archive_dir, account, video_id):
    """加载 Layer 1 预处理产出（Whisper STT + ffprobe + Baseline）"""
    payload_path = os.path.join(archive_dir, account, "videos", video_id, "_grounding_payload.json")
    if os.path.exists(payload_path):
        with open(payload_path) as f:
            return json.load(f)
    return None


def check_placeholder_forgery(data):
    """占位符/空串伪造检测（2026-07-27 AccountA07-09 伪造交付事故新增）。

    背景：07/08/09 用骨架条目过闸——shot description="Shot 1"、quote="Quote 1"、
    VO/SFX text 全空串、honesty evidence="Saw everything"/"Detail"——条目级字段存在性
    校验全绿但内容零信息量。本门禁查内容真实性签名，任一命中拒收。
    """
    import re as _re
    _PH = _re.compile(r"^(shot|quote|scene|detail|segment|beat|clip|item|entry)[ _-]?\d*$", _re.I)
    issues = []

    # 1) shot_timeline 描述占位符
    shots = data.get("cinematography", {}).get("shot_timeline", [])
    ph = sum(1 for s in shots if isinstance(s, dict)
             and _PH.match(str(s.get("visual_content") or s.get("description") or "").strip()))
    if ph:
        issues.append(f"shot_timeline 含 {ph} 条占位符描述（'Shot N' 同款）——非真实逐镜观察，拒收")

    # 1b) shot_timeline 模板套话/骨架填充语（"第N镜XX画面细节描述"类，2026-07-28 AccountA10/08 骨架事故：
    #     旧正则只锚定纯英文 'Shot N'，漏掉带描述性后缀的中文骨架，被密度门放行）
    _TPL = _re.compile(r"画面细节描述|画面描述|细节描述|此处描述|详见画面|内容描述|待补|(?<![无非板])占位|placeholder|TBD", _re.I)
    _vc = lambda s: str(s.get("visual_content") or s.get("description") or "") if isinstance(s, dict) else ""
    tpl_hits = sum(1 for s in shots if _TPL.search(_vc(s)))
    if tpl_hits:
        issues.append(f"shot_timeline 含 {tpl_hits} 条模板套话（'画面细节描述'类填充语）——非真实观察骨架，拒收")

    # 1c) shot_timeline 去数字后唯一度过低（模板骨架：每镜仅编号不同，如'第1镜…'/'第2镜…'）
    stripped = [_re.sub(r"[\d.\s]+", "", _vc(s)).strip() for s in shots]
    stripped = [v for v in stripped if v]
    if len(stripped) >= 8:
        uniq = len(set(stripped))
        if uniq < max(3, len(stripped) * 0.5):
            issues.append(f"shot_timeline visual_content 去数字后仅 {uniq}/{len(stripped)} 唯一——疑似模板骨架（每镜仅编号不同），拒收")

    # 2) VO 空串条目
    vo = data.get("audio", {}).get("voiceover_transcript", [])
    empty_vo = sum(1 for v in vo if isinstance(v, dict) and not str(v.get("text") or "").strip())
    if vo and (empty_vo >= 5 or empty_vo / len(vo) >= 0.2):
        issues.append(f"voiceover_transcript {empty_vo}/{len(vo)} 条 text 为空串——凑条数骗密度门禁，拒收")

    # 3) SFX 空描述条目（字段回退链含 name：01号存量资产用 name 且内容真实，避免误伤）
    sfx = data.get("audio", {}).get("sfx_timeline", [])
    empty_sfx = sum(1 for s in sfx if isinstance(s, dict)
                    and not str(s.get("description") or s.get("sfx_name") or s.get("name") or "").strip())
    if sfx and (empty_sfx >= 5 or empty_sfx / len(sfx) >= 0.2):
        issues.append(f"sfx_timeline {empty_sfx}/{len(sfx)} 条无描述/名称——凑条数骗密度门禁，拒收")

    # 4) 金句占位符
    quotes = data.get("narrative", {}).get("all_quotes", [])
    ph_q = sum(1 for q in quotes if _PH.match(str(
        (q.get("quote_text") or q.get("text") or "") if isinstance(q, dict) else q).strip()))
    if ph_q:
        issues.append(f"all_quotes 含 {ph_q} 条占位符（'Quote N' 同款）——金句必须是视频原文，拒收")

    # 5) honesty evidence 硬检（仅对声称 view_file_watched=true 的板块）
    hr = data.get("_meta", {}).get("honesty_report", {})
    for name, sec in (hr.get("sections") or {}).items():
        if not (isinstance(sec, dict) and sec.get("view_file_watched") is True):
            continue
        ev = str(sec.get("evidence") or "").strip()
        if len(ev) < 30:
            issues.append(f"honesty.{name}.evidence 仅 {len(ev)} 字符（'{ev[:20]}'）——真实观看证据不可能这么短，拒收")
        details = sec.get("specific_details_only_from_watching") or []
        ph_d = sum(1 for d in details if isinstance(d, str) and _PH.match(d.strip()))
        if ph_d:
            issues.append(f"honesty.{name}.specific_details 含 {ph_d} 条占位符（'Detail' 同款）——拒收")
    return issues


def run_hard_gate_checks(data):
    """物理级硬门禁：任一不过则直接打回，不进入 Pro 审查"""
    issues = []

    # Schema 必填板块
    for section in SECTIONS:
        if section not in data:
            issues.append(f"板块 '{section}' 缺失")

    # 板块内 top 必填字段（契约唯一事实源；空/缺失均视为未填）
    for section, fields in SECTION_TOP_FIELDS.items():
        sec_data = data.get(section)
        if not isinstance(sec_data, dict):
            continue  # 板块整体缺失已在上面记录
        for field in fields:
            val = sec_data.get(field)
            if val is None or val == [] or val == {} or val == "":
                issues.append(f"{section}.{field} 缺失或为空（契约 top 必填）")

    # 诚实度报告存在性与铁律字段
    hr = data.get("_meta", {}).get("honesty_report", {})
    if not hr:
        issues.append("honesty_report 缺失")
    else:
        if hr.get("script_generated") is True:
            issues.append("script_generated = true（使用了脚本生成）")
        # SKILL.md 铁律：view_file_called 为 false 整条 JSON 作废
        if hr.get("view_file_called") is not True:
            issues.append("honesty_report.view_file_called 非 true（铁律：未真实调用 view_file，整条作废）")
        if hr.get("watched_full_video") is not True:
            issues.append("honesty_report.watched_full_video 非 true（未观看完整视频）")

    # 镜头数 vs macro
    shots = data.get("cinematography", {}).get("shot_timeline", [])
    total_shots = data.get("cinematography", {}).get("macro", {}).get("total_shots", 0)
    if total_shots != len(shots):
        issues.append(f"macro.total_shots ({total_shots}) != len(shot_timeline) ({len(shots)})")

    # 占位符/空串伪造签名（2026-07-27 新增，ingest 复核与阶段A 双路拦截）
    issues.extend(check_placeholder_forgery(data))

    return issues


def evaluate_honesty(data):
    """规则预检：诚实度维度（50%）— 读取嵌套 schema：honesty_report.sections.<板块>

    注意：本检查只能发现"结构性不诚实"（缺字段/过短/无时间点），
    无法验证 evidence 是否属实——后者由 Pro 3.1 独立观看视频抽查完成。
    """
    hr = data.get("_meta", {}).get("honesty_report", {})
    score = 100
    issues = []

    if hr.get("script_generated") is True:
        score -= 50
        issues.append("script_generated = true，严重违规")

    sections = hr.get("sections", {})
    if not sections:
        score -= 30
        issues.append("honesty_report.sections 缺失（应为嵌套结构：sections.<板块>.evidence，见 SKILL.md 示例）")
    else:
        for sec_name in SECTIONS:
            sec = sections.get(sec_name)
            if not isinstance(sec, dict):
                score -= 6
                issues.append(f"sections.{sec_name} 缺失")
                continue
            if sec.get("view_file_watched") is not True:
                score -= 5
                issues.append(f"{sec_name}: view_file_watched 非 true")
            ev = sec.get("evidence", "")
            if not isinstance(ev, str) or len(ev) < 30:
                score -= 6
                issues.append(f"{sec_name}: evidence 缺失或过短（<{len(ev) if isinstance(ev, str) else 0}字符），疑似泛化")
            elif not any(c.isdigit() for c in ev):
                score -= 3
                issues.append(f"{sec_name}: evidence 无时间点")
            details = sec.get("specific_details_only_from_watching", [])
            if len(details) < 3:
                score -= 3
                issues.append(f"{sec_name}: specific_details 数量不足（{len(details)}/3）")

    return max(0, score), issues


def evaluate_audio_visual_logic(data):
    """规则预检：声画自洽性维度（50%）"""
    score = 100
    issues = []

    cine = data.get("cinematography", {})
    audio = data.get("audio", {})
    narr = data.get("narrative", {})
    shots = cine.get("shot_timeline", [])
    if not isinstance(shots, list):
        shots = []
    shots = [sh for sh in shots if isinstance(sh, dict)]

    # VO vs script_full_text（模糊匹配：difflib 相似度 >= 0.85 视为匹配）
    vo = audio.get("voiceover_transcript", [])
    if not isinstance(vo, list):
        vo = []
    script = narr.get("script_full_text", "")
    vo_concat = re.sub(r"\s+", "", " ".join(v.get("text", "") for v in vo if isinstance(v, dict)))
    script_norm = re.sub(r"\s+", "", script)
    if script_norm and vo_concat:
        ratio = difflib.SequenceMatcher(None, vo_concat, script_norm).ratio()
        if ratio < 0.85:
            score -= 10
            issues.append(f"VO 拼接文本与 script_full_text 相似度 {ratio:.0%}（< 85%）")

    # SFX vs 镜头区间
    sfx = audio.get("sfx_timeline", [])
    if not isinstance(sfx, list):
        sfx = []
    for s in sfx:
        if not isinstance(s, dict):
            continue
        t = s.get("second", 0)
        in_shot = any(sh.get("start_sec", 0) <= t <= sh.get("end_sec", 0) for sh in shots)
        if not in_shot and shots:
            score -= 5
            issues.append(f"SFX at {t}s 不在任何镜头区间内")

    # BGM vs 情绪曲线
    bgm = audio.get("bgm_timeline", [])
    emotions = narr.get("emotional_timeline", [])
    if not isinstance(bgm, list):
        bgm = []
    if not isinstance(emotions, list):
        emotions = []
    for b in bgm:
        if not isinstance(b, dict):
            continue
        t = b.get("second", 0)
        aligned = any(e.get("start_sec", 0) <= t <= e.get("end_sec", 0) for e in emotions if isinstance(e, dict)) if emotions else False
        if not aligned and emotions:
            score -= 3
            issues.append(f"BGM 变化 at {t}s 未对齐情绪曲线")

    # Ducking vs SFX 对齐
    ducking = audio.get("ducking_and_silence", audio.get("silence_moments", []))
    if isinstance(ducking, dict):
        ducking = [ducking]
    elif not isinstance(ducking, list):
        ducking = []  # 软字段(top_soft)：AI 可能产出字符串描述，非结构化则跳过对齐检查
    sfx_times = [s.get("second", 0) for s in sfx if isinstance(s, dict)]
    for d in ducking:
        if not isinstance(d, dict):
            continue
        t = d.get("second", 0)
        if sfx_times:
            closest = min(sfx_times, key=lambda x: abs(x - t))
            if abs(t - closest) > 1:
                score -= 3
                issues.append(f"Ducking at {t}s 与最近 SFX (at {closest}s) 偏差 >1s")

    # 镜头覆盖全片
    if shots:
        last_end = shots[-1].get("end_sec", 0)
        duration = data.get("_meta", {}).get("duration_sec", 0)
        if duration and abs(last_end - duration) > 1:
            score -= 10
            issues.append(f"镜头覆盖到 {last_end}s，视频时长 {duration}s，差距 >1s")

    # climax vs reversal
    macro = narr.get("macro", {}).get("attention_curve", {})
    if isinstance(macro, dict):
        climax = macro.get("climax_sec", "")
        reversal = macro.get("reversal_sec", "")
        if climax and reversal and climax == reversal:
            score -= 5
            issues.append("climax_sec 和 reversal_sec 相同")
    elif isinstance(narr.get("macro", {}), dict):
        macro_obj = narr.get("macro", {})
        climax = macro_obj.get("climax_sec", "")
        reversal = macro_obj.get("reversal_sec", "")
        if climax and reversal and climax == reversal:
            score -= 5
            issues.append("climax_sec 和 reversal_sec 相同")

    return max(0, score), issues


def cross_validate_whisper_vo(data, grounding):
    """Whisper STT 交叉验证：校验 voiceover_transcript 对 Ground Truth 的覆盖率

    从 _grounding_payload.json 读取 whisper_stt（Layer 1 Whisper STT），
    与 Flash 产出的 audio.voiceover_transcript 做逐段时间重叠+文本模糊匹配，
    计算 VO 覆盖率（>= 70% 为合格）。低于阈值则扣分。

    Returns:
        (score_adjustment, issues, coverage_data)
        coverage_data: {"stt_segments": N, "vo_covered": M, "coverage_rate": 0.XX, "missed": [...]}
    """
    if not grounding:
        return 0, [], None

    whisper_stt = grounding.get("whisper_stt", [])
    if not whisper_stt or not isinstance(whisper_stt, list):
        return 0, [], None

    vo_items = data.get("audio", {}).get("voiceover_transcript", [])
    if isinstance(vo_items, str):
        vo_items = [{"text": vo_items, "start_sec": 0, "end_sec": 9999}]
    elif isinstance(vo_items, list):
        norm_vo = []
        for item in vo_items:
            if isinstance(item, dict):
                norm_vo.append(item)
            elif isinstance(item, str):
                norm_vo.append({"text": item, "start_sec": 0, "end_sec": 9999})
        vo_items = norm_vo

    if not vo_items:
        return -10, ["voiceover_transcript 为空，无法做 Whisper 交叉验证"], {
            "stt_segments": len(whisper_stt), "vo_covered": 0,
            "coverage_rate": 0.0, "missed": [s.get("text", "")[:60] for s in whisper_stt[:5]]
        }

    # 归一化文本：去空白和标点
    def normalize(text):
        return re.sub(r"[\s\W]", "", text.lower())

    # 为每个 STT 段寻找时间重叠 + 文本相似的 VO 段
    matched = 0
    missed_segments = []
    for stt_seg in whisper_stt:
        stt_text = normalize(stt_seg.get("text", ""))
        stt_start = stt_seg.get("start_sec", 0)
        stt_end = stt_seg.get("end_sec", 0)

        found = False
        for vo in vo_items:
            vo_text = normalize(vo.get("text", ""))
            vo_start = vo.get("start_sec", 0)
            vo_end = vo.get("end_sec", 0)

            # 时间重叠检查
            time_overlap = stt_start < vo_end and stt_end > vo_start
            if not time_overlap:
                continue

            # 短文本（单字/单词）只要时间重叠就算覆盖
            if len(stt_text) <= 5:
                found = True
                break

            # 文本相似度（模糊匹配，>= 0.5 视为覆盖）
            if stt_text and vo_text:
                ratio = difflib.SequenceMatcher(None, stt_text, vo_text).ratio()
                if ratio >= 0.5:
                    found = True
                    break

        if found:
            matched += 1
        else:
            missed_segments.append({
                "stt_text": stt_seg.get("text", "")[:80],
                "stt_time": f"{stt_start:.1f}-{stt_end:.1f}s",
            })

    total = len(whisper_stt)
    coverage_rate = matched / total if total > 0 else 0.0

    issues = []
    score_adj = 0
    if coverage_rate < 0.70:
        score_adj = -10
        issues.append(
            f"Whisper VO 覆盖率 {coverage_rate:.0%}（< 70%），"
            f"{len(missed_segments)}/{total} 段 STT 未被 voiceover_transcript 覆盖"
        )

    coverage_data = {
        "stt_segments": total,
        "vo_covered": matched,
        "coverage_rate": round(coverage_rate, 2),
        "missed": missed_segments[:10],
    }

    return score_adj, issues, coverage_data



def generate_target_probes(issues_by_dim):
    """从规则 issue 生成兜底探针（Pro 未给出探针时使用）"""
    probes = []

    for dim_name, issues in issues_by_dim.items():
        for issue in issues:
            target_sec = "00.00-END"
            match = re.search(r"at (\d+\.?\d*)s", issue)
            if match:
                t = float(match.group(1))
                target_sec = f"{max(0, t - 5):.2f}-{t + 5:.2f}"

            section = "unknown"
            if "honesty" in dim_name:
                section = "_meta.honesty_report"
            elif "SFX" in issue or "BGM" in issue or "VO" in issue or "Ducking" in issue:
                section = "audio"
            elif "shot" in issue.lower() or "镜头" in issue:
                section = "cinematography"
            elif "climax" in issue or "reversal" in issue or "情绪" in issue:
                section = "narrative"

            probes.append({
                "section": section,
                "target_sec": target_sec,
                "question": issue,
            })

    return probes


def build_review_packet(data, json_path, grounding, rule_results, account, video_id, date, whisper_xval=None, analysis_md5=None):
    """组装 Pro 3.1 审查包"""
    h_score, h_issues = rule_results["honesty"]
    av_score, av_issues = rule_results["audio_visual_logic"]

    return {
        "packet_type": "pro_review_request",
        "version": 2,
        "account": account,
        "video_id": video_id,
        "analysis_date": date,
        "analysis_path": json_path,
        "analysis_md5": analysis_md5,
        "analysis": data,
        "grounding": grounding or {},
        "rule_prescan": {
            "honesty": {"score": h_score, "issues": h_issues},
            "audio_visual_logic": {"score": av_score, "issues": av_issues},
            "whisper_cross_validation": whisper_xval or {},
        },
        "pro_instructions": (
            "你是 Gemini 3.1 Pro 质检员，对 Flash 3.6 产出的视频分析 JSON 做语义级终审。必须完成三件事：\n"
            "1.【视频抽查 · 诚实度终审】用 view_file 独立观看该视频（加载路径优先取 grounding.view_file_target——"
            "大文件已转码为 _sense.mp4 感知轨，与 Flash 所见一致且防上传断管；无该字段再用归档目录原片），"
            "从 honesty_report.sections 每个板块抽查至少 1 条 specific_details_only_from_watching / evidence，"
            "核验其在视频中是否真实存在。抽查结果写入 spot_check（details_sampled / details_verified / mismatches）。"
            "发现编造 → score ≤ 50。\n"
            "2.【语义级审查】检查声画脱节（SFX/BGM/Ducking 与画面事件是否真实对齐）、因果矛盾"
            "（镜头描述与叙事节拍是否自洽）、偷懒模板（跨条目雷同句式）。问题写入 semantic_issues。\n"
            "3.【VO 交叉验证】对照 grounding.whisper_stt（Whisper Ground Truth）校验 voiceover_transcript 的"
            "覆盖度与准确度，严重漏句/错句 → 扣分并生成探针。\n"
            "对 score < 90 的疑点，生成 target_probes（section + target_sec ±5s + 具体语义问题），"
            "供 Flash 定点重看修补，不要泛泛打回。\n"
            "输出严格 JSON：{\"score\": 0-100, \"verdict\": \"pass|fail\", \"spot_check\": {...}, "
            "\"semantic_issues\": [...], \"target_probes\": [{\"section\", \"target_sec\", \"question\"}]}"
        ),
    }


def validate_pro_result(result):
    """校验 Pro 审查结果 schema，返回 (ok, error_message)"""
    if not isinstance(result, dict):
        return False, "结果不是 JSON 对象"
    score = result.get("score")
    if not isinstance(score, (int, float)) or not (0 <= score <= 100):
        return False, "score 缺失或越界（必须为 0-100 数值）"
    # 伪造 stub 拦截（2026-07-27 AccountA07-09：184 字节 stub 自评 98 分畅通）
    sc = result.get("spot_check")
    if not isinstance(sc, dict):
        return False, "spot_check 缺失——Pro 阶段B 必须真实 view_file 抽查并回报明细"
    # details_sampled 兑容 int(计数) 或 list(明细列表)；list 形态更难伪造，回退看 total_sampled_count
    ds = sc.get("details_sampled")
    if isinstance(ds, list):
        ds_count = len(ds)
    elif isinstance(ds, int):
        ds_count = ds
    elif isinstance(sc.get("total_sampled_count"), int):
        ds_count = sc.get("total_sampled_count")
    else:
        ds_count = 0
    if ds_count < 3:
        return False, "spot_check 抽查明细 < 3（每板块抽查 ≥1 条，5 板块至少 3 条）"
    # mismatches 兑容嵌在 spot_check 内 或 顶层
    mm = sc.get("mismatches")
    if mm is None:
        mm = result.get("mismatches")
    if not isinstance(mm, list):
        return False, "mismatches 缺失或非数组（可为空数组，但字段必存，在 spot_check 内或顶层均可）"
    probes = result.get("target_probes", [])
    if probes and not isinstance(probes, list):
        return False, "target_probes 必须为数组"
    for p in probes:
        if not isinstance(p, dict) or "question" not in p:
            return False, "target_probes 条目缺 question 字段"
    return True, None


def drive_state_machine(archive_dir, account, video_id, date, qa_passed, score, result, state_path):
    """更新状态机：PASS_DELIVERED / PROBE_REPAIRING / FAILED_CIRCUIT_BROKEN"""
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)

    retry_count = count_repairs(state)

    if qa_passed:
        # 幂等：已交付不重复追加
        append_state(state_path, "PASS_DELIVERED")
        state["current_state"] = "PASS_DELIVERED"
    else:
        if retry_count >= MAX_RETRIES:
            append_state(state_path, "FAILED_CIRCUIT_BROKEN")
            state["current_state"] = "FAILED_CIRCUIT_BROKEN"
            print(f"\n⚠️ 熔断！已重试 {retry_count} 次仍未通过，写入失败库")
            failed_path = os.path.join(archive_dir, account, f"_failed_{date}.json")
            failed_list = []
            if os.path.exists(failed_path):
                with open(failed_path) as f:
                    failed_list = json.load(f)
            failed_list.append({"video_id": video_id, "reason": f"熔断：{retry_count}次未达标", "score": score})
            with open(failed_path, "w") as f:
                json.dump(failed_list, f, ensure_ascii=False, indent=2)
            result["message"] = f"熔断：{retry_count} 次修补仍未达 {PASS_THRESHOLD} 分，已写入失败库"
        else:
            state["current_state"] = "PROBE_REPAIRING"
            state.setdefault("history", []).append({"state": "PROBE_REPAIRING", "timestamp": datetime.now().isoformat(), "retry": retry_count + 1})
            with open(state_path, "w") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"\n第 {retry_count + 1}/{MAX_RETRIES} 次修补，Flash 需针对探针定点重看")

    return state["current_state"]


def main():
    parser = argparse.ArgumentParser(description="Layer 3 Pro 质检器（两阶段：规则硬门禁 → Pro 语义审查）")
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", required=True, help="账号名")
    parser.add_argument("--video-id", required=True, help="视频ID")
    parser.add_argument("--date", help="分析日期 YYYY-MM-DD（ingest 阶段可省略，自动取最新）")
    parser.add_argument("--show-result", action="store_true", help="仅显示已有审查结果")
    parser.add_argument("--emit-review-packet", action="store_true", help="阶段A：硬门禁+规则预检，产出 Pro 审查包（默认行为）")
    parser.add_argument("--ingest-pro-result", action="store_true", help="阶段B：回收 Pro 审查结果，驱动状态机")
    parser.add_argument("--skip-review-interval-check", action="store_true",
                        help="跨过最小审查间隔拦截（仅限重新组包导致的误拦，须在交付摘要说明理由）")
    parser.add_argument("--rule-only", action="store_true", help="仅用规则评分（快速预检，不得作为交付依据）")
    args = parser.parse_args()

    video_dir = os.path.join(args.archive_dir, args.account, "videos", args.video_id)
    qa_path = os.path.join(video_dir, "_qa_result.json")
    state_path = os.path.join(video_dir, "_state.json")
    packet_path = os.path.join(video_dir, "_pro_review_packet.json")
    pro_result_path = os.path.join(video_dir, "_pro_review_result.json")

    if args.show_result:
        if os.path.exists(qa_path):
            with open(qa_path) as f:
                print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
        else:
            print("❌ 无审查结果")
        return

    # ── 阶段B：回收 Pro 审查结果 ──
    if args.ingest_pro_result:
        if not os.path.exists(pro_result_path):
            print(f"❌ Pro 审查结果不存在: {pro_result_path}")
            print("   请先将 _pro_review_packet.json 交给 Pro 3.1 审查，产出该文件")
            sys.exit(1)
        with open(pro_result_path) as f:
            pro_result = json.load(f)
        ok, err = validate_pro_result(pro_result)
        if not ok:
            print(f"❌ Pro 结果 schema 不合规: {err}")
            sys.exit(1)

        # 伪造 stub 体积拦截（2026-07-27：真实 Pro 终审结果含抽查明细/语义问题，实测 ≥2.9KB；
        # 伪造件仅 184 字节骨架。阈值 600B 留足安全边距）
        result_size = os.path.getsize(pro_result_path)
        if result_size < 600:
            print(f"❌ Pro 结果仅 {result_size} 字节（<600B）——真实抽查必含逐条明细，疑似伪造 stub，拒收")
            print("   Pro 阶段B 必须真实 view_file 观看视频并回报 spot_check 明细（参照 SKILL.md 示例）")
            sys.exit(1)

        # 最小审查间隔拦截（2026-07-27：08/09 号组包后 13-14 秒即交回 98 分“终审”——
        # 真实抽查须 view_file 观看视频，物理上不可能 <60s）
        if os.path.exists(packet_path) and not args.skip_review_interval_check:
            gap_sec = os.path.getmtime(pro_result_path) - os.path.getmtime(packet_path)
            if gap_sec < 60:
                print(f"❌ Pro 结果与审查包间隔仅 {gap_sec:.0f}s（<60s）——真实 view_file 抽查物理上不可能这么快，拒收")
                print("   如系重新组包导致的误拦（结果早于包），请重新执行阶段B 审查；确认审查真实可加 --skip-review-interval-check 跨过（须在交付摘要中说明理由）")
                sys.exit(1)

        # 加载被审查的分析 JSON（用于硬门禁复核与日期确定）
        if args.date:
            data, json_path = load_analysis_json(args.archive_dir, args.account, args.video_id, args.date)
            date = args.date
        else:
            data, json_path, date = find_latest_analysis(args.archive_dir, args.account, args.video_id)
        if not data:
            sys.exit(1)

        # md5 一致性校验：防止拿旧审查包审新数据（修补后必须重新组包）
        packet = {}
        if os.path.exists(packet_path):
            with open(packet_path) as f:
                packet = json.load(f)
        packet_md5 = packet.get("analysis_md5")
        current_md5 = file_md5(json_path)
        if packet_md5 and packet_md5 != current_md5:
            print("❌ analysis 文件在组包后被修改，当前审查包已过期")
            print(f"   packet md5:  {packet_md5}")
            print(f"   current md5: {current_md5}")
            print("   请先重新执行阶段A 组包，再将新包交给 Pro 审查")
            sys.exit(1)
        elif not packet_md5:
            print("⚠️ 审查包缺 analysis_md5（旧版包），跳过一致性校验")

        hard_issues = run_hard_gate_checks(data)
        pro_score = round(pro_result["score"])
        qa_passed = pro_score >= PASS_THRESHOLD and not hard_issues

        # 轮次号 = 已记录修补次数 + 1（不按 PRO_AUDITING 次数，避免重复组包导致错位）
        state_pre = {}
        if os.path.exists(state_path):
            with open(state_path) as f:
                state_pre = json.load(f)
        round_no = count_repairs(state_pre) + 1

        # 轮次归档：Pro 结果保留历史副本，防止被下轮覆盖丢失审计轨迹
        archived_pro = os.path.join(video_dir, f"_pro_review_result_r{round_no}.json")
        shutil.copy2(pro_result_path, archived_pro)

        # dimensions：阶段A 规则预检两维分数带入正式结果（下游统一 schema）
        prescan = packet.get("rule_prescan", {})
        dimensions = {
            "honesty": prescan.get("honesty", {}),
            "audio_visual_logic": prescan.get("audio_visual_logic", {}),
            "whisper_cross_validation": prescan.get("whisper_cross_validation", {}),
            "pro_semantic_score": pro_score,
        }

        result = {
            "qa_passed": qa_passed,
            "score": pro_score,
            "review_mode": "pro_semantic",
            "round": round_no,
            "pro_result": pro_result,
            "hard_gate_issues": hard_issues,
            "dimensions": dimensions,
        }

        if qa_passed:
            result["message"] = "Pro 质检通过，进入 Layer 4 交付"
            print(f"🟢 GREEN — Pro 质检通过（{pro_score}/100），进入 Layer 4 交付")
        else:
            probes = pro_result.get("target_probes") or generate_target_probes({
                "hard_gate": hard_issues,
                "pro_semantic": pro_result.get("semantic_issues", []),
            })
            result["target_probes"] = probes
            reason = f"Pro 评分 {pro_score}/{PASS_THRESHOLD}" if pro_score < PASS_THRESHOLD else "硬门禁复核未通过"
            result["message"] = f"质检未通过（{reason}），请 Flash 针对探针定点重看并修补"
            print(f"🔴 RED — {result['message']}")
            for probe in probes:
                print(f"   - [{probe.get('section', '?')}] {probe.get('target_sec', '?')}s: {probe['question']}")

        with open(qa_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n审查结果已保存: {qa_path}")

        drive_state_machine(args.archive_dir, args.account, args.video_id, date, qa_passed, pro_score, result, state_path)
        # 状态机可能熔断改写 message，回写最终版
        with open(qa_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        # QA 结果轮次归档（与 Pro 结果同轮次号）
        archived_qa = os.path.join(video_dir, f"_qa_result_r{round_no}.json")
        shutil.copy2(qa_path, archived_qa)
        print(f"轮次归档: r{round_no} → {os.path.basename(archived_pro)}, {os.path.basename(archived_qa)}")
        sys.exit(0 if qa_passed else 1)

    # ── 阶段A：硬门禁 + 规则预检 + 组装审查包（默认）──
    if not args.date:
        print("❌ 阶段A 必须指定 --date")
        sys.exit(1)
    data, json_path = load_analysis_json(args.archive_dir, args.account, args.video_id, args.date)
    if not data:
        sys.exit(1)

    print("=" * 60)
    print("Layer 3 质检 · 阶段A（规则预检）")
    print(f"视频: {args.video_id}")
    print("=" * 60)

    # 0. Layer 3 入口状态校验（合法集：FLASH_EXTRACTED / PROBE_REPAIRING / PRO_AUDITING）
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
    current_state = state.get("current_state", "")
    if current_state and current_state not in L3_ENTRY_STATES:
        print(f"❌ GATE FAIL: current_state={current_state}，Layer 3 入口要求 {sorted(L3_ENTRY_STATES)}")
        print("   请先完成上一层（Layer 2 Flash 感知）或检查状态机")
        sys.exit(1)

    # 0.05 状态篡改快速检测（完整检测用 session_guard.py validate-state）
    if "attempts" in state:
        print("⚠️ 警告：_state.json 含 'attempts' 字段——脚本从不写此字段，疑似 Agent 手写")
        print("   建议运行: python3 scripts/session_guard.py validate-state")
        print("   未来请用 session_guard.py mark-flash-extracted 替代手写 _state.json")
    history = state.get("history", [])
    if not isinstance(history, list) or len(history) == 0:
        print("⚠️ 警告：_state.json 无 'history' 数组——脚本总是写 history，疑似手写或截断")
    # 早产标记检测：FLASH_EXTRACTED 距 PREPROCESSED < 60s（L2 需 10-45 分钟）
    if current_state == "FLASH_EXTRACTED" and isinstance(history, list):
        pre_ts = next((h.get("timestamp") for h in history if h.get("state") == "PREPROCESSED"), None)
        flash_ts = next((h.get("timestamp") for h in history if h.get("state") == "FLASH_EXTRACTED"), None)
        if pre_ts and flash_ts:
            try:
                delta = (datetime.fromisoformat(flash_ts) - datetime.fromisoformat(pre_ts)).total_seconds()
                if delta < 60:
                    print(f"⚠️ 警告：FLASH_EXTRACTED 距 PREPROCESSED 仅 {delta:.0f}s（L2 需 10-45 分钟），疑似早产标记")
                    print("   建议用 session_guard.py mark-flash-extracted 重新标记（幂等）")
            except (ValueError, TypeError):
                pass

    # 0.1 修补感知：旧审查包存在且 analysis 已被修改 → 记 PROBE_REPAIRING（手动/自动修补都留痕）
    current_md5 = file_md5(json_path)
    repair_sensed = False
    if os.path.exists(packet_path):
        try:
            with open(packet_path) as f:
                old_packet = json.load(f)
            old_md5 = old_packet.get("analysis_md5")
        except json.JSONDecodeError:
            old_md5 = None
        if old_md5 and old_md5 != current_md5 and current_state != "PROBE_REPAIRING":
            repairs = count_repairs(state) + 1
            if repairs > MAX_RETRIES:
                state["current_state"] = "FAILED_CIRCUIT_BROKEN"
                state.setdefault("history", []).append({
                    "state": "FAILED_CIRCUIT_BROKEN",
                    "timestamp": datetime.now().isoformat(),
                    "reason": f"修补超过 {MAX_RETRIES} 次",
                })
                with open(state_path, "w") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                print(f"🔴 熔断：修补已超过 {MAX_RETRIES} 次，写入 _failed_{args.date}.json")
                failed_path = os.path.join(args.archive_dir, args.account, f"_failed_{args.date}.json")
                failed_list = []
                if os.path.exists(failed_path):
                    with open(failed_path) as f:
                        failed_list = json.load(f)
                failed_list.append({"video_id": args.video_id, "reason": f"熔断：{MAX_RETRIES} 次修补未达标", "score": None})
                with open(failed_path, "w") as f:
                    json.dump(failed_list, f, ensure_ascii=False, indent=2)
                sys.exit(1)
            state["current_state"] = "PROBE_REPAIRING"
            state.setdefault("history", []).append({
                "state": "PROBE_REPAIRING",
                "timestamp": datetime.now().isoformat(),
                "retry": repairs,
                "trigger": "analysis_md5_changed（组包间隔内 analysis 被修补）",
            })
            with open(state_path, "w") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            current_state = "PROBE_REPAIRING"
            repair_sensed = True
            print(f"\n🔧 感知到修补（第 {repairs}/{MAX_RETRIES} 轮）：analysis 与旧审查包不一致，已记录 PROBE_REPAIRING")

    # 1. 物理级硬门禁
    print("\n1. 物理级硬门禁...")
    hard_issues = run_hard_gate_checks(data)
    if hard_issues:
        print(f"   ❌ {len(hard_issues)} 个硬门禁问题:")
        for issue in hard_issues:
            print(f"      - {issue}")
        result = {
            "qa_passed": False,
            "score": 0,
            "review_mode": "hard_gate",
            "hard_gate_issues": hard_issues,
            "message": "硬门禁未通过，需 Flash 全量重新感知",
        }
        with open(qa_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n🔴 RED — 硬门禁未通过，Score: 0")
        drive_state_machine(args.archive_dir, args.account, args.video_id, args.date, False, 0, result, state_path)
        with open(qa_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(1)
    print("   ✅ 硬门禁通过")

    # 2. 规则预检（二维）
    print("\n2. 规则预检（结构层，语义终审由 Pro 完成）...")
    h_score, h_issues = evaluate_honesty(data)
    print(f"   [诚实度结构预检] {h_score}/100")
    for issue in h_issues:
        print(f"      - {issue}")
    av_score, av_issues = evaluate_audio_visual_logic(data)
    print(f"   [声画自洽预检] {av_score}/100")
    for issue in av_issues:
        print(f"      - {issue}")

    # Whisper 交叉验证（VO 覆盖率 — 用起 Layer 1 Ground Truth）
    grounding = load_grounding_payload(args.archive_dir, args.account, args.video_id)
    whisper_adj, whisper_issues, whisper_data = cross_validate_whisper_vo(data, grounding)
    if whisper_data:
        av_score = max(0, av_score + whisper_adj)
        av_issues.extend(whisper_issues)
        print(f"   [Whisper VO 交叉验证] 覆盖率: {whisper_data['coverage_rate']:.0%} ({whisper_data['vo_covered']}/{whisper_data['stt_segments']} 段)")
        for issue in whisper_issues:
            print(f"      - {issue}")

    # 3a. --rule-only：快速预检模式（不得作为交付依据）
    if args.rule_only:
        total_score = round(h_score * 0.5 + av_score * 0.5)
        qa_passed = total_score >= PASS_THRESHOLD
        result = {
            "qa_passed": qa_passed,
            "score": total_score,
            "review_mode": "rule_only（快速预检，未经 Pro 语义审查，不得作为交付依据）",
            "dimensions": {
                "honesty": {"score": h_score, "issues": h_issues},
                "audio_visual_logic": {"score": av_score, "issues": av_issues},
                "whisper_cross_validation": whisper_data or {},
            },
            "message": "规则预检通过（仍需 Pro 语义终审）" if qa_passed else f"规则预检未通过（{total_score}/{PASS_THRESHOLD}）",
        }
        if not qa_passed:
            result["target_probes"] = generate_target_probes({"honesty": h_issues, "audio_visual_logic": av_issues})
        with open(qa_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n{'🟢' if qa_passed else '🔴'} 规则预检总分: {total_score}/100（注意：未经 Pro 终审）")
        drive_state_machine(args.archive_dir, args.account, args.video_id, args.date, qa_passed, total_score, result, state_path)
        with open(qa_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(0 if qa_passed else 1)

    # 3b. 默认：组装 Pro 审查包
    print("\n3. 组装 Pro 审查包...")
    if not grounding:
        print("   ⚠️ _grounding_payload.json 缺失，Pro 将无法做 Whisper 交叉验证（建议先补跑 Layer 1）")
    packet = build_review_packet(
        data, json_path, grounding,
        {"honesty": (h_score, h_issues), "audio_visual_logic": (av_score, av_issues)},
        args.account, args.video_id, args.date,
        whisper_xval=whisper_data,
        analysis_md5=current_md5,
    )
    with open(packet_path, "w") as f:
        json.dump(packet, f, ensure_ascii=False, indent=2)
    print(f"   ✅ 审查包: {packet_path}（analysis_md5: {current_md5[:8]}...）")

    # 状态置为 PRO_AUDITING（幂等：已处于 PRO_AUDITING 时不重复追加）
    append_state(state_path, "PRO_AUDITING")

    print("\n" + "=" * 60)
    print("下一步（阶段B · 必须执行）：")
    print("1. 将 _pro_review_packet.json 交给 Gemini 3.1 Pro，按 pro_instructions 完成：")
    print("   ① 独立 view_file 观看视频，抽查每板块 ≥1 条 specific_details/evidence 是否属实")
    print("   ② 语义级审查（声画脱节/因果矛盾/偷懒模板）")
    print("   ③ 对照 Whisper STT 校验 VO 转录")
    print(f"2. Pro 产出 _pro_review_result.json 到: {video_dir}/")
    print("3. 回收结果：")
    print(f"   python3 pro_qa_inspector.py --ingest-pro-result \\")
    print(f"     --archive-dir {args.archive_dir} --account {args.account} --video-id {args.video_id}")


if __name__ == "__main__":
    main()
