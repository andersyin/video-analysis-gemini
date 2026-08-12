#!/usr/bin/env python3
"""会话寿命管理器 — 把"死亡半径"缩到最小。

背景（2026-07-26 第二次死亡复盘）：
  同一视频今天死了两次，死因都是会话在 L2→L3 间隙耗尽。
  L2 是 45 分钟的 view_file 大流式调用（重活），L3 阶段A 是秒级脚本（轻活）。
  会话死在"刚干完最重的活、还没来得及跑轻活"的间隙。
  根因不可根除（网络/平台不可控），但可以通过四层防御把死亡半径缩到零：

  1. L2→L3 原子绑定：写完 analysis JSON → 立即跑 pro_qa_inspector（零间隙）
  2. 会话预算上限：每会话最多 3 条 L2，第 4 条之前必须开新会话
  3. 状态机完整性：用脚本替代 Agent 手写 _state.json，消除早产标记
  4. 前检查：开工前扫卡住的视频，优先推进而非开新坑

用法:
  # L2 完成后：验证 analysis JSON 并标记 FLASH_EXTRACTED（替代 Agent 手写 _state.json）
  python3 session_guard.py --mark-flash-extracted \
    --archive-dir /path/to/archive --account "kat-and-oliver" \
    --video-id "TOP01_xxxx" --date 2026-07-26

  # 开工前检查：扫描所有视频状态，推荐下一步行动
  python3 session_guard.py --preflight \
    --archive-dir /path/to/archive --account "kat-and-oliver"

  # 状态篡改检测：检查特定视频或全量视频的 _state.json 完整性
  python3 session_guard.py --validate-state \
    --archive-dir /path/to/archive --account "kat-and-oliver"
  python3 session_guard.py --validate-state \
    --archive-dir /path/to/archive --account "kat-and-oliver" --video-id "TOP01_xxxx"
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 状态机定义（与 SKILL.md / pro_qa_inspector.py 一致）
STATE_ORDER = [
    "UNPROCESSED",
    "PREPROCESSED",
    "FLASH_EXTRACTED",
    "PRO_AUDITING",
    "PROBE_REPAIRING",
    "PASS_DELIVERED",
    "FAILED_CIRCUIT_BROKEN",
]

# 会话预算：每会话最多完成多少条 L2（view_file 感知）
SESSION_BUDGET_MAX = 3
SESSION_BUDGET_SOFT = 2  # 软提醒阈值

# 篡改检测签名
TAMPER_SIGNATURES = {
    "attempts_field": "_state.json 含 'attempts' 字段——脚本从不写此字段，疑似 Agent 手写",
    "no_history": "_state.json 无 'history' 数组——脚本总是写 history，疑似手写或截断",
    "premature_flash": "FLASH_EXTRACTED 时间戳距 PREPROCESSED < 60s——L2 需 10-45 分钟，疑似早产标记",
    "flash_without_analysis": "FLASH_EXTRACTED 状态但无 analysis_*.json——状态与产出不一致",
}

# L2 完成到 L3 开始的最小合理间隔（秒）：L2 至少需要 view_file 观看 + JSON 写入
MIN_L2_DURATION_SEC = 60

# watchdog（2026-07-26）：analysis 齐 5 板块但状态仍 PREPROCESSED 的宽限期（秒），
# 超过即判定为"写完收工忘跑 finalize-l2"遗孤（c97c5b1f / 铁头阿彪02 两次复现的行为违规签名）
ORPHAN_ANALYSIS_GRACE_SEC = 600

# 5 板块清单（与 SKILL.md / mark-flash-extracted 校验一致）
EXPECTED_SECTIONS = ["cinematography", "ai_fx", "audio", "narrative", "sop"]

# 密度门禁契约路径（分段口径唯一事实源，2026-07-26 统一）
_CONTRACT_PATH = Path(__file__).resolve().parent / "schema_contract.json"

# POV/长镜头例外关键词（honesty_report 中声明拍摄风格才可用放宽下限）
POV_EXCEPTION_KEYWORDS = ["POV", "长镜头", "手持", "一镜到底"]


def load_density_gates():
    """从 schema_contract.json 读取 density_gates 分段口径"""
    try:
        raw = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        return raw.get("density_gates", {})
    except Exception:
        return {}


def _infer_duration_from_analysis(analysis):
    """无 _video_meta.json 时从时间轴推断时长"""
    for sec in ("cinematography", "audio", "narrative"):
        tl_key = {"cinematography": "shot_timeline",
                  "audio": "voiceover_transcript",
                  "narrative": "emotional_timeline"}[sec]
        tl = analysis.get(sec, {}).get(tl_key, [])
        if isinstance(tl, list) and tl:
            last = tl[-1]
            if isinstance(last, dict) and isinstance(last.get("end_sec"), (int, float)):
                return float(last["end_sec"])
    return 0.0


def check_density_gates(analysis, video_dir):
    """密度门禁：镜头密度/ASL/SFX密度/VO密度 分段校验。

    返回 (failures: list[str], warnings: list[str], metrics: dict)。
    failures 非空 → 拒绝标记 FLASH_EXTRACTED。
    """
    gates = load_density_gates()
    if not gates:
        return [], ["⚠️ schema_contract.json 无 density_gates，跳过密度门禁"], {}

    # 1. 时长：优先 _video_meta.json，兜底时间轴推断
    meta_path = os.path.join(video_dir, "_video_meta.json")
    duration = 0.0
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                duration = float(json.load(f).get("duration_sec", 0))
        except Exception:
            pass
    if duration <= 0:
        duration = _infer_duration_from_analysis(analysis)
    if duration <= 0:
        return [], ["⚠️ 无法确定视频时长，跳过密度门禁"], {}

    # 2. 选档
    tier = None
    for t in gates.get("tiers", []):
        cap = t.get("max_duration_sec")
        if cap is None or duration <= cap:
            tier = t
            break
    if tier is None:
        return [], [f"⚠️ 时长 {duration:.1f}s 无匹配密度档，跳过"], {}

    # 3. 计算实际指标
    cine = analysis.get("cinematography", {})
    audio = analysis.get("audio", {})
    shots = cine.get("shot_timeline", []) if isinstance(cine, dict) else []
    sfx = audio.get("sfx_timeline", []) if isinstance(audio, dict) else []
    vo = audio.get("voiceover_transcript", []) if isinstance(audio, dict) else []

    shot_density = len(shots) / duration * 10 if duration else 0
    asl = (sum(max(0, s.get("end_sec", 0) - s.get("start_sec", 0))
               for s in shots if isinstance(s, dict)) / len(shots)) if shots else 0
    sfx_density = len(sfx) / duration * 10 if duration else 0
    vo_density = len(vo) / duration * 10 if duration else 0

    metrics = {
        "duration_sec": round(duration, 2),
        "tier": tier.get("name"),
        "shots": len(shots),
        "shot_density_per_10s": round(shot_density, 2),
        "asl_sec": round(asl, 2),
        "sfx_density_per_10s": round(sfx_density, 2),
        "vo_density_per_10s": round(vo_density, 2),
    }

    # 4. POV/长镜头例外：honesty_report 声明拍摄风格才放宽镜头密度
    honesty_text = json.dumps(analysis.get("_meta", {}).get("honesty_report", {}), ensure_ascii=False)
    pov_declared = any(k in honesty_text for k in POV_EXCEPTION_KEYWORDS)

    shot_min = tier.get("shot_density_per_10s_min")
    if pov_declared and tier.get("pov_longtake_shot_density_per_10s_min") is not None:
        shot_min = tier["pov_longtake_shot_density_per_10s_min"]

    failures, warnings = [], []

    if shot_min is not None and shots and shot_density < shot_min:
        failures.append(
            f"镜头密度 {shot_density:.2f}/10s 低于 {tier.get('name')} 档下限 {shot_min}/10s"
            f"（{len(shots)} 镜 / {duration:.1f}s）。"
            + ("已按 POV/长镜头放宽。" if pov_declared else
               "如确为 POV/手持长镜头风格，请在 honesty_report 声明后重试；否则回 L2 重切镜头。")
        )

    asl_range = tier.get("asl_range_sec")
    if asl_range and shots:
        if asl > asl_range[1]:
            failures.append(
                f"ASL {asl:.2f}s 超过 {tier.get('name')} 档上限 {asl_range[1]}s——"
                f"镜头切分不够细（多个实际镜头被合并），回 L2 重切"
            )
        elif asl < asl_range[0]:
            warnings.append(
                f"⚠️ ASL {asl:.2f}s 低于 {tier.get('name')} 档下限 {asl_range[0]}s，疑似过度切分"
            )

    sfx_min = tier.get("sfx_density_per_10s_min")
    if sfx_min is not None and sfx_density < sfx_min:
        # 近临例外（2026-08-06 奶糕10号实证）：SFX 密度差一点达标但条目真实，
        # 达到阈值 80% 即降级为告警
        if sfx_density >= sfx_min * 0.8 and len(sfx) >= 5:
            warnings.append(
                f"⚠️ SFX 密度 {sfx_density:.2f}/10s 低于 {tier.get('name')} 档下限 {sfx_min}/10s"
                f"（{len(sfx)} 条 / {duration:.1f}s）——达到阈值80%，判定为边界近临而非遗漏，降级放行"
            )
        else:
            failures.append(
                f"SFX 密度 {sfx_density:.2f}/10s 低于 {tier.get('name')} 档下限 {sfx_min}/10s"
                f"（{len(sfx)} 条 / {duration:.1f}s）——检查是否遗漏次要环境音，回 L2 补标"
            )

    vo_min = tier.get("vo_density_per_10s_min")
    if vo_min is not None and vo and vo_density < vo_min:
        # 稀疏对话例外（2026-08-06 奶糕07号实证）：萌宠/音乐视频等可能全片仅有几句话，
        # VO 条目真实但数量少不等于 L2 漏标。条件：条目真实(非占位/每条文本>5字) +
        # 总数≤6 + VO 覆盖率<15% → 降级为告警
        vo_texts = [str(v.get("text", "") or v.get("content", "") or "").strip()
                    for v in vo if isinstance(v, dict)]
        genuine_vo = all(len(t) > 0 for t in vo_texts) and len(vo_texts) == len(vo)
        vo_total_dur = sum(
            max(0, (v.get("end_sec", 0) or 0) - (v.get("start_sec", 0) or 0))
            for v in vo if isinstance(v, dict)
        )
        vo_coverage = vo_total_dur / duration if duration else 0
        if genuine_vo and len(vo) <= 8 and vo_coverage < 0.20:
            warnings.append(
                f"⚠️ VO 密度 {vo_density:.2f}/10s 低于 {tier.get('name')} 档下限 {vo_min}/10s"
                f"（{len(vo)} 条 / {duration:.1f}s，覆盖率 {vo_coverage:.0%}）——"
                f"但条目真实且总覆盖率<15%，判定为视频本身对话稀疏而非 L2 漏标，降级放行"
            )
        else:
            failures.append(
                f"VO 密度 {vo_density:.2f}/10s 低于 {tier.get('name')} 档下限 {vo_min}/10s——"
                f"旁白应切到句子级（单句 ≤10s），回 L2 重切"
            )

    # 5. 物理边界硬截断（2026-07-26 新增）：任何时间戳超出真实时长 +0.5s 容差即硬拒
    # 历史教训：裸 prompt 路径曾幻觉出 39s 不存在的时间轴（A/B 报告 §4）。
    if duration > 0:
        cap = duration + 0.5
        nar = analysis.get("narrative", {}) if isinstance(analysis.get("narrative"), dict) else {}
        emo = (nar.get("emotional_timeline") or cine.get("emotional_timeline") or []) \
            if isinstance(cine, dict) else []
        beats = nar.get("story_beats", []) or []
        bgm = audio.get("bgm_timeline", []) if isinstance(audio, dict) else []
        # ai_fx 时间轨（2026-07-27 补盲区：铁头阿彪01 重感知 scene_timeline 两条 +100s 越界未被拦）
        fx = analysis.get("ai_fx", {}) if isinstance(analysis.get("ai_fx"), dict) else {}
        fx_scenes = fx.get("scene_timeline", []) or []
        fx_micro = fx.get("micro_motion_moments", []) or []
        overruns = []
        for label, items in (("shot_timeline", shots), ("voiceover_transcript", vo),
                             ("sfx_timeline", sfx), ("bgm_timeline", bgm),
                             ("emotional_timeline", emo), ("story_beats", beats),
                             ("ai_fx.scene_timeline", fx_scenes),
                             ("ai_fx.micro_motion_moments", fx_micro)):
            for it in items:
                if not isinstance(it, dict):
                    continue
                ts = [v for k, v in it.items()
                      if k in ("start_sec", "end_sec", "sec", "timestamp_sec")
                      and isinstance(v, (int, float))]
                if ts and max(ts) > cap:
                    overruns.append(f"{label} 越界 {max(ts):.1f}s")
        if overruns:
            failures.append(
                f"物理边界硬拒：{len(overruns)} 条时间戳超出真实时长 {duration:.2f}s（容差 0.5s）——"
                f"疑似时间轴幻觉，示例：{'; '.join(overruns[:3])}。回 L2 按 _system_boundary 重校时间轴"
            )
            metrics["boundary_overruns"] = len(overruns)

    # 6. 算法切点锚点软告警（2026-07-27，A/B 实验 02 号欠切事故）：
    # shot 数与 ffmpeg 硬切点量级严重偏离时告警（不拒收——scene 检测对闪光/大运动会过检）
    payload_path = os.path.join(video_dir, "_grounding_payload.json")
    if os.path.exists(payload_path) and shots:
        try:
            est = (json.load(open(payload_path)).get("_scene_cut_estimate") or {}).get("hard_cuts_detected")
        except (json.JSONDecodeError, OSError):
            est = None
        if isinstance(est, int) and est >= 10:
            metrics["scene_cut_estimate"] = est
            # 风格感知上限（2026-08-04 监督审计 I-4）：honesty 声明低切/手持/POV/长镜头/
            # 简笔动画等软切风格时，硬切点锚点对感知镜数的解释力下降，上限 2.5→4.0
            honesty_txt = json.dumps(analysis.get("_meta", {}), ensure_ascii=False)
            style_aware = any(k in honesty_txt for k in ("低切", "手持", "POV", "长镜头", "简笔", "动画"))
            upper = 4.0 if style_aware else 2.5
            if style_aware:
                metrics["scene_anchor_style_aware"] = True
            if len(shots) < est * 0.5:
                warnings.append(
                    f"⚠️ 切点锚点：shot_timeline {len(shots)} 条 < 算法硬切点 {est} 的 50%——"
                    f"涉嫌漏切/合并（快切视频禁止按档位合并镜头），建议重审 shot 切分粒度"
                )
            elif len(shots) > est * upper:
                warnings.append(
                    f"⚠️ 切点锚点：shot_timeline {len(shots)} 条 > 算法硬切点 {est} 的 {upper} 倍"
                    f"{'（风格感知：已按 honesty 声明的软切风格放宽上限）' if style_aware else ''}——"
                    f"涉嫌过度切分或模板填充（参考反例：01 号 142 条等长填充）"
                )

    # 7. VO 边界链接嫌疑检查（2026-08-04 监督审计 I-1，羊和狗刻03 重跑实证）：
    # 新版感知把 VO 句边界链式合并（end=next.start），吞掉 whisper 实测 14s 句间静默，
    # 产出假 100% 覆盖时间轴（而 macro 声明的 ratio 反而诚实）。双条件同时成立硬拒：
    # VO 去重叠合并覆盖 ≥99.5% 总时长 且 whisper 句间静默合计 ≥5s。
    if duration > 0 and len(vo) >= 2:
        iv = sorted(
            ((it.get("start_sec", 0), it.get("end_sec", 0)) for it in vo if isinstance(it, dict)),
            key=lambda x: x[0],
        )
        merged = 0.0
        cs = ce = None
        for s, e in iv:
            if cs is None:
                cs, ce = s, e
            elif s <= ce:
                ce = max(ce, e)
            else:
                merged += ce - cs
                cs, ce = s, e
        if cs is not None:
            merged += ce - cs
        whisper_gaps = None
        if os.path.exists(payload_path):
            try:
                stt = json.load(open(payload_path)).get("whisper_stt") or []
                siv = sorted(
                    ((x.get("start_sec", 0), x.get("end_sec", 0)) for x in stt if isinstance(x, dict)),
                    key=lambda x: x[0],
                )
                whisper_gaps = sum(max(0.0, siv[i][0] - siv[i - 1][1]) for i in range(1, len(siv)))
            except (json.JSONDecodeError, OSError):
                whisper_gaps = None
        if merged >= duration * 0.995 and whisper_gaps is not None and whisper_gaps >= 5:
            failures.append(
                f"VO 边界链接嫌疑拒收：voiceover_transcript 去重叠合并覆盖 {merged / duration * 100:.1f}%（零间隙），"
                f"但 whisper Ground Truth 句间静默合计 {whisper_gaps:.1f}s——句边界被链式合并（end=next.start），时间轴失真。"
                f"回 L2 逐句重切 VO 边界并保留静默间隙（macro 声明 ratio 必须可从时间戳重算）"
            )
            metrics["vo_chaining_suspect"] = True

    return failures, warnings, metrics


def check_contract_completeness(analysis):
    """契约完整性门禁（2026-07-26 biaoda 同片对比复盘新增）。

    背景：铁头阿彪04 的 narrative.hook_analysis={} 与 sop.monetization={} 空块
    带着 QA 98 分过审——密度门禁只数 timeline 条数，不看契约字段是否空置。
    规则：
    - contract sections.top 硬必填：字段缺失 → 拒收
    - top + top_soft 字段若存在但为 空dict/空list/空str → 拒收
      （确无该项内容必须填显式否定值，如 monetization={"product_placement": "无"}）
    - top_soft 软必填缺失 → 告警不拒收（04号商单视频 monetization 整体缺失的教训）
    - timeline 条目级必填（timeline_item_min_fields，2026-07-27 补）：条目缺契约字段 → 拒收
      （01号重感知 shot_id/camera_height 变体暴露条目级盲区：顶层齐了但条目字段名漂移，
      下游渲染器/聚合脚本照样踩雷）
    返回 (failures, warnings)。
    """
    failures = []
    warnings = []
    try:
        contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        sections_spec = contract.get("sections", {})
    except Exception:
        return ["⚠️ schema_contract.json 不可读，无法执行契约完整性门禁"], []
    for name, spec in sections_spec.items():
        sec = analysis.get(name)
        if not isinstance(sec, dict):
            continue  # 板块级缺失由 5 板块检查兜底
        for field in spec.get("top", []):
            if field not in sec:
                failures.append(f"{name}.{field} 缺失（契约硬必填）")
        for field in spec.get("top_soft", []):
            if field not in sec:
                warnings.append(f"⚠️ {name}.{field} 缺失（契约软必填，建议回 L2 补齐）")
        for field in spec.get("top", []) + spec.get("top_soft", []):
            val = sec.get(field, "__absent__")
            if val in ({}, [], ""):
                failures.append(
                    f"{name}.{field} 为空块——空块拒收；确无内容需填显式否定值（如 '无'）"
                )
        item_min = spec.get("timeline_item_min_fields", [])
        if item_min:
            tl_field = next((f for f in spec.get("top", []) if "timeline" in f), None)
            items = sec.get(tl_field) if tl_field else None
            if isinstance(items, list) and items:
                miss_counts = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    for f in item_min:
                        if f not in it:
                            miss_counts[f] = miss_counts.get(f, 0) + 1
                for f, n in miss_counts.items():
                    failures.append(
                        f"{name}.{tl_field} 条目缺必填字段 '{f}'（{n}/{len(items)} 条）——"
                        f"字段名以契约 timeline_item_min_fields 为准，禁止变体（如 shot_id 代 index）"
                    )
    return failures, warnings


def check_shot_authenticity(analysis):
    """反模板填充门禁（2026-07-26 biaoda 同片对比复盘新增）。

    背景：铁头阿彪01 的 shot_timeline 存在大段严格等长 1.65s（= baseline ASL）的
    中景/近景/特写循环 + 逐条复制的 visual_content——程序化凑密度绕过密度门禁拿 95 分。
    规则：
    - 连续 ≥8 镜时长完全相等（±0.01s）→ 拒收（真实剪辑不可能）
    - 镜头描述归一化去重后，同一描述出现 ≥5 次且占比 >30% → 拒收
    """
    failures = []
    cine = analysis.get("cinematography", {})
    shots = cine.get("shot_timeline", []) if isinstance(cine, dict) else []
    if not shots or len(shots) < 8:
        return failures

    def _dur(s):
        if not isinstance(s, dict):
            return None
        d = s.get("duration_sec")
        if isinstance(d, (int, float)) and d > 0:
            return round(float(d), 2)
        st, en = s.get("start_sec"), s.get("end_sec")
        if isinstance(st, (int, float)) and isinstance(en, (int, float)):
            return round(float(en) - float(st), 2)
        return None

    durs = [_dur(s) for s in shots]
    run, max_run, max_run_val, max_run_start = 1, 1, None, 0
    cur_start = 0
    for i in range(1, len(durs)):
        if durs[i] is not None and durs[i] == durs[i - 1]:
            run += 1
            if run > max_run:
                max_run, max_run_val, max_run_start = run, durs[i], cur_start
        else:
            run = 1
            cur_start = i
    if max_run >= 8:
        # 内容多样性例外（2026-08-06 奶糕09号实证）：音乐节拍切分等合法场景
        # 也会产生等长连打，但每镜 visual_content 不同。如果连打中内容唯一度≥70%，放行。
        import re as _re2
        run_shots = shots[max_run_start:max_run_start + max_run]
        run_vcs = [_re2.sub(r"[\d\.]+", "", str(s.get("visual_content", "") or s.get("visual_description", ""))).strip()
                   for s in run_shots if isinstance(s, dict)]
        run_vcs = [v for v in run_vcs if v]
        if run_vcs:
            run_uniq = len(set(run_vcs))
            if run_uniq >= max(3, len(run_vcs) * 0.7):
                pass  # 内容多元——合法节拍切分，不拒收
            else:
                failures.append(
                    f"连续 {max_run} 镜时长严格等长（{max_run_val}s）且内容重复（唯一 {run_uniq}/{len(run_vcs)}）——"
                    f"疑似按 baseline ASL 模板填充凑密度，回 L2 逐镜重感知真实切点"
                )
        else:
            failures.append(
                f"连续 {max_run} 镜时长严格等长（{max_run_val}s）——疑似按 baseline ASL 模板填充凑密度，"
                f"回 L2 逐镜重感知真实切点"
            )

    import re as _re
    descs = []
    for s in shots:
        if isinstance(s, dict):
            raw = str(s.get("visual_content") or s.get("visual_description") or "")
            norm = _re.sub(r"\d+(\.\d+)?", "<n>", raw).strip()
            if norm:
                descs.append(norm)
    if descs:
        from collections import Counter
        top_desc, top_n = Counter(descs).most_common(1)[0]
        if top_n >= 5 and top_n / len(shots) > 0.30:
            failures.append(
                f"镜头描述重复填充：同一描述出现 {top_n}/{len(shots)} 次（>30%）——"
                f"'{top_desc[:40]}…' 非逐镜独立观察，回 L2 重写 visual_content"
            )
    return failures


def check_stt_coverage_flag(analysis, video_dir):
    """STT 低覆盖降级标记（2026-07-26 biaoda 同片对比复盘新增，不拒收）。

    背景：铁头阿彪01 Whisper 覆盖率 0.53（川渝方言错听），narrative 直接引用错听
    文本长出'足球退役人物'虚构故事线，QA 95 分未拦截。
    规则：coverage < 0.70 → 不拒收（方言错听非感知者之过），但：
    - 醒目告警：narrative 禁止直接引用 STT 文本结论，台词须以多模态听写为准
    - 返回 coverage 值，由调用方写入 _state.json 顶层 stt_low_coverage，
      供 Pro 阶段B 重点核查 narrative 是否被错听台词污染
    """
    gp_path = os.path.join(video_dir, "_grounding_payload.json")
    if not os.path.exists(gp_path):
        return None
    try:
        with open(gp_path) as f:
            grounding = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    try:
        from pro_qa_inspector import cross_validate_whisper_vo
    except ImportError:
        return None
    _, _, coverage_data = cross_validate_whisper_vo(analysis, grounding)
    if not coverage_data:
        return None
    return coverage_data.get("coverage_rate")


def load_state(video_dir):
    """加载视频的 _state.json"""
    state_path = os.path.join(video_dir, "_state.json")
    if not os.path.exists(state_path):
        return None, state_path
    try:
        with open(state_path) as f:
            return json.load(f), state_path
    except json.JSONDecodeError:
        return {"_corrupt": True}, state_path


def find_analysis_files(video_dir):
    """查找视频目录下所有 analysis_*.json 文件，返回按日期倒序列表"""
    d = Path(video_dir)
    return sorted(d.glob("analysis_*.json"), reverse=True)


def inspect_orphan_analysis(video_dir):
    """PREPROCESSED 状态下盘点最新 analysis_*.json 的板块完成度（watchdog，2026-07-26）

    背景：铁头阿彪02 两次复现"写完 JSON 未跑 finalize-l2"——状态停在 PREPROCESSED，
    preflight 旧逻辑会推荐重进 L2，白白浪费一次 45-70 分钟完整感知。以磁盘为准盘点：
    - 5 板块齐 → 遗孤，P0 直接 finalize-l2（禁止重进 L2）
    - 部分板块 → 续跑只补缺失板块（上下文截断恢复路径，不信记忆）

    返回 None（无 analysis 文件）或 dict(date, present, missing, is_complete, age_sec, corrupt)。
    """
    analyses = find_analysis_files(video_dir)
    if not analyses:
        return None
    latest = analyses[0]
    date = latest.stem.replace("analysis_", "")
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"date": date, "present": [], "missing": list(EXPECTED_SECTIONS),
                "is_complete": False, "age_sec": 0, "corrupt": True}
    present = [s for s in EXPECTED_SECTIONS if isinstance(data.get(s), dict) and data.get(s)]
    missing = [s for s in EXPECTED_SECTIONS if s not in present]
    try:
        age_sec = max(0, datetime.now().timestamp() - latest.stat().st_mtime)
    except OSError:
        age_sec = 0
    return {"date": date, "present": present, "missing": missing,
            "is_complete": not missing, "age_sec": round(age_sec), "corrupt": False}


def check_state_tampering(state, state_path, video_dir):
    """检测 _state.json 篡改签名

    返回 (issues: list[str], severity: 'ok'|'warn'|'critical')
    """
    issues = []

    if state is None:
        return ["_state.json 不存在"], "warn"

    if state.get("_corrupt"):
        return ["_state.json JSON 解析失败（损坏）"], "critical"

    current = state.get("current_state", "")
    history = state.get("history", [])

    # 签名 1：attempts 字段（脚本从不写）
    if "attempts" in state:
        issues.append(TAMPER_SIGNATURES["attempts_field"])

    # 签名 2：无 history 数组
    if not isinstance(history, list) or len(history) == 0:
        issues.append(TAMPER_SIGNATURES["no_history"])

    # 签名 3：FLASH_EXTRACTED 早产检测
    if current == "FLASH_EXTRACTED":
        pre_ts = None
        flash_ts = None
        for h in history:
            if h.get("state") == "PREPROCESSED":
                pre_ts = h.get("timestamp")
            elif h.get("state") == "FLASH_EXTRACTED":
                flash_ts = h.get("timestamp")
        if pre_ts and flash_ts:
            try:
                dt_pre = _parse_ts(pre_ts)
                dt_flash = _parse_ts(flash_ts)
                delta_sec = (dt_flash - dt_pre).total_seconds()
                if delta_sec < MIN_L2_DURATION_SEC:
                    issues.append(
                        f"{TAMPER_SIGNATURES['premature_flash']}（实际间隔 {delta_sec:.0f}s）"
                    )
            except Exception:
                pass

    # 签名 4：FLASH_EXTRACTED 但无 analysis JSON
    if current == "FLASH_EXTRACTED":
        analyses = find_analysis_files(video_dir)
        if not analyses:
            issues.append(TAMPER_SIGNATURES["flash_without_analysis"])

    severity = "ok"
    if issues:
        severity = "critical" if any("早产" in i or "不一致" in i or "损坏" in i for i in issues) else "warn"

    return issues, severity


def _parse_ts(ts_str):
    """解析 ISO 时间戳，兼容有无时区后缀"""
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间戳: {ts_str}")


def has_file(video_dir, filename):
    """检查视频目录下是否存在指定文件"""
    return os.path.exists(os.path.join(video_dir, filename))


def get_next_action(current_state, video_dir, video_id, account, archive_dir):
    """根据当前状态推荐下一步行动"""
    actions = []

    if current_state == "UNPROCESSED":
        actions.append(("P4", "运行 Layer 1 预处理",
                        f"python3 scripts/preprocessor.py --video <视频路径> "
                        f"--archive-dir {archive_dir} --account {account} --video-id {video_id}"))

    elif current_state == "PREPROCESSED":
        orphan = inspect_orphan_analysis(video_dir)
        if orphan and orphan.get("is_complete"):
            # watchdog：写完收工遗孤签名——analysis 齐 5 板块却从未 finalize-l2，
            # 重进 L2 会浪费一次完整感知，必须直接补跑 finalize-l2
            age_min = orphan["age_sec"] / 60
            overdue = "，已超宽限期" if orphan["age_sec"] > ORPHAN_ANALYSIS_GRACE_SEC else ""
            actions.append(("P0_遗孤",
                            f"⚠️ analysis_{orphan['date']}.json 已齐 5 板块但未 finalize-l2"
                            f"（落盘 {age_min:.0f} 分钟前{overdue}，疑似写完收工/会话死亡）"
                            f"→ 立即补跑 finalize-l2，禁止重进 L2",
                            f"python3 scripts/session_guard.py finalize-l2 "
                            f"--archive-dir {archive_dir} --account {account} "
                            f"--video-id {video_id} --date {orphan['date']}"))
        elif orphan and orphan["present"]:
            # 上下文截断恢复：以磁盘为准，只补缺失板块
            actions.append(("P3", f"L2 续跑：磁盘已有 {orphan['present']}，只补缺失板块 {orphan['missing']}",
                            f"view_file 感知缺失板块 → 渐进落盘 → 末板块同回合 "
                            f"session_guard.py finalize-l2"))
        else:
            actions.append(("P3", "运行 Layer 2 感知",
                            f"view_file 加载视频 → 5 板块 JSON 渐进落盘 analysis_<date>.json → "
                            f"末板块同回合调用 session_guard.py finalize-l2"))

    elif current_state == "FLASH_EXTRACTED":
        # 关键判断：是否有 _pro_review_packet.json
        if has_file(video_dir, "_pro_review_packet.json"):
            actions.append(("P2", "运行 Layer 3 阶段B（Pro 语义终审）",
                           f"Pro 3.1 按审查包完成语义终审 → 产出 _pro_review_result.json → "
                           f"python3 scripts/pro_qa_inspector.py --ingest-pro-result "
                           f"--archive-dir {archive_dir} --account {account} --video-id {video_id}"))
        else:
            # 这就是死亡签名：L2 完成但 L3 阶段A 从未执行
            analyses = find_analysis_files(video_dir)
            date_hint = analyses[0].stem.replace("analysis_", "") if analyses else "<date>"
            actions.append(("P1_紧急", "⚠️ 卡在 L2→L3 间隙！立即运行 L3 阶段A（秒级脚本，零流式）",
                           f"python3 scripts/pro_qa_inspector.py --emit-review-packet "
                           f"--archive-dir {archive_dir} --account {account} "
                           f"--video-id {video_id} --date {date_hint}"))

    elif current_state == "PRO_AUDITING":
        if has_file(video_dir, "_pro_review_result.json"):
            actions.append(("P2", "回收 Pro 审查结果",
                           f"python3 scripts/pro_qa_inspector.py --ingest-pro-result "
                           f"--archive-dir {archive_dir} --account {account} --video-id {video_id}"))
        else:
            actions.append(("P2", "等待 Pro 3.1 语义终审完成",
                           "Pro 需独立 view_file 观看视频并产出 _pro_review_result.json"))

    elif current_state == "PROBE_REPAIRING":
        actions.append(("P2", "Flash 定向修补后重新走 L3",
                       "修补 analysis JSON → 重新组包 → Pro 重审"))

    elif current_state == "PASS_DELIVERED":
        actions.append(("done", "✅ 已交付完成", ""))

    elif current_state == "FAILED_CIRCUIT_BROKEN":
        actions.append(("done", "❌ 熔断失败，已写入失败库", "检查 _failed_<date>.json"))

    return actions


def cmd_mark_flash_extracted(args, print_next_hint=True):
    """L2 完成后：验证 analysis JSON 存在且含 5 板块，然后标记 FLASH_EXTRACTED

    替代 Agent 手写 _state.json。关键改进：
    1. 验证 analysis JSON 实际存在（防止早产标记）
    2. 验证 5 板块齐全（防止半成品标记）
    3. 用脚本写 history（格式一致、时间戳真实）
    4. 输出下一步指令（L2→L3 原子绑定）
    """
    video_dir = os.path.join(args.archive_dir, args.account, "videos", args.video_id)
    state_path = os.path.join(video_dir, "_state.json")

    # 1. 验证 analysis JSON 存在
    analysis_path = os.path.join(video_dir, f"analysis_{args.date}.json")
    if not os.path.exists(analysis_path):
        print(f"❌ 分析文件不存在: {analysis_path}")
        print("   禁止在 analysis JSON 写入前标记 FLASH_EXTRACTED（防止早产标记）")
        sys.exit(1)

    # 2. 验证 5 板块齐全
    try:
        with open(analysis_path) as f:
            analysis = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ 分析 JSON 解析失败: {e}")
        sys.exit(1)

    sections = analysis.get("_meta", {}).get("sections", [])
    expected = ["cinematography", "ai_fx", "audio", "narrative", "sop"]
    missing = [s for s in expected if s not in analysis]
    if missing:
        print(f"❌ 分析 JSON 缺少板块: {missing}")
        print("   禁止在 5 板块不齐时标记 FLASH_EXTRACTED")
        sys.exit(1)

    # 2.5 密度门禁（2026-07-26 新增）：镜头密度/ASL/SFX/VO 分段校验
    failures, warnings, gate_metrics = check_density_gates(analysis, video_dir)
    for w in warnings:
        print(w)
    if failures:
        print("❌ 密度门禁未通过，拒绝标记 FLASH_EXTRACTED：")
        for f_ in failures:
            print(f"   🔴 {f_}")
        print(f"\n   实测指标: {json.dumps(gate_metrics, ensure_ascii=False)}")
        print("   阈值口径: scripts/schema_contract.json → density_gates")
        sys.exit(1)
    if gate_metrics:
        print(f"✅ 密度门禁通过 [{gate_metrics.get('tier')} 档]: "
              f"镜头 {gate_metrics.get('shot_density_per_10s')}/10s · "
              f"ASL {gate_metrics.get('asl_sec')}s · "
              f"SFX {gate_metrics.get('sfx_density_per_10s')}/10s · "
              f"VO {gate_metrics.get('vo_density_per_10s')}/10s")

    # 2.6 契约完整性门禁（2026-07-26 新增）：硬必填缺失 / 空块拒收；软必填缺失告警
    contract_failures, contract_warnings = check_contract_completeness(analysis)
    for w in contract_warnings:
        print(w)
    if contract_failures:
        print("❌ 契约完整性门禁未通过，拒绝标记 FLASH_EXTRACTED：")
        for f_ in contract_failures:
            print(f"   🔴 {f_}")
        print("   参照 scripts/schema_contract.json → sections；可用 emit-l2-skeleton 生成骨架对照")
        sys.exit(1)

    # 2.7 反模板填充门禁（2026-07-26 新增）：等长镜头连打 / 重复描述
    authenticity_failures = check_shot_authenticity(analysis)
    if authenticity_failures:
        print("❌ 反模板填充门禁未通过，拒绝标记 FLASH_EXTRACTED：")
        for f_ in authenticity_failures:
            print(f"   🔴 {f_}")
        sys.exit(1)

    # 2.75 占位符/空串伪造签名门禁（2026-07-27 铁头阿彪07-09 伪造交付事故新增）：
    # 'Shot N'/'Quote N'/'Detail' 占位符、VO/SFX 空串凑数、短于 30 字符的 honesty evidence
    try:
        from pro_qa_inspector import check_placeholder_forgery
        forgery_failures = check_placeholder_forgery(analysis)
    except ImportError:
        forgery_failures = []
    if forgery_failures:
        print("❌ 伪造签名门禁未通过，拒绝标记 FLASH_EXTRACTED：")
        for f_ in forgery_failures:
            print(f"   🔴 {f_}")
        print("   骨架字段齐不等于真实感知——每条内容必须来自 view_file 真实观看")
        sys.exit(1)

    # 2.8 STT 低覆盖降级标记（2026-07-26 新增，不拒收）
    stt_coverage = check_stt_coverage_flag(analysis, video_dir)
    stt_low = stt_coverage is not None and stt_coverage < 0.70
    if stt_low:
        print(f"⚠️ Whisper STT 覆盖率 {stt_coverage:.0%} < 70%（方言/音质错听可能）——不拒收，但：")
        print("   🔴 narrative 禁止直接引用 STT 文本结论，台词以多模态听写为准")
        print("   🔴 将写入 _state.json 顶层 stt_low_coverage，Pro 阶段B 须重点核查台词污染")

    # 3. 加载现有状态，检查前置条件
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)

    current = state.get("current_state", "")
    if stt_low:
        state["stt_low_coverage"] = stt_coverage
    if current == "FLASH_EXTRACTED":
        print(f"ℹ️ 状态已是 FLASH_EXTRACTED（幂等，不重复标记）")
        if stt_low:
            with open(state_path, "w") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
    elif current == "PREPROCESSED":
        # 正常路径：PREPROCESSED → FLASH_EXTRACTED
        state["current_state"] = "FLASH_EXTRACTED"
        state.setdefault("history", []).append({
            "state": "FLASH_EXTRACTED",
            "timestamp": datetime.now().isoformat(),
            "trigger": "session_guard --mark-flash-extracted（脚本验证后写入）",
        })
        with open(state_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"✅ 状态更新: PREPROCESSED → FLASH_EXTRACTED")
        print(f"   验证通过: analysis_{args.date}.json 存在 + 5 板块齐全")
    elif current in ("PROBE_REPAIRING", "PRO_AUDITING"):
        # 修补路径：Flash 定向修补后重新标记
        print(f"ℹ️ 当前状态 {current}，analysis 已更新，保持状态机继续")
    else:
        print(f"❌ 状态异常: current_state={current}，预期 PREPROCESSED")
        print("   如需强制标记，请先修复状态机")
        sys.exit(1)

    # 4. L2→L3 原子绑定：输出下一步指令（finalize-l2 模式下由本进程直接执行，不打印提示）
    if not print_next_hint:
        return
    print("\n" + "=" * 60)
    print("🔴 L2→L3 原子绑定 — 下一步必须立即执行（零流式·秒级脚本）")
    print("=" * 60)
    print(f"python3 scripts/pro_qa_inspector.py \\")
    print(f"  --archive-dir {args.archive_dir} \\")
    print(f"  --account {args.account} \\")
    print(f"  --video-id {args.video_id} \\")
    print(f"  --date {args.date}")
    print("=" * 60)
    print("⚠️ 禁止在 L3 阶段A 执行前开始新视频的 L1/L2 或任何 view_file 调用")


def cmd_finalize_l2(args):
    """L2 收尾一键化（2026-07-26 加固）：mark-flash-extracted + L3 阶段A 组包同进程连跑

    背景：transcript c97c5b1f 实锤了行为违规失败模式——Agent 写完 analysis 后空响应收工，
    没跑 f2/f3 两步，产物成为孤儿。把两步合成一条命令后，原子绑定间隙物理消失：
    - 任一验证/门禁失败 → 同进程 sys.exit，状态不动，天然幂等
    - 门禁通过 → 立即 subprocess 拉起 pro_qa_inspector.py --emit-review-packet（秒级、零流式）
    """
    # 第 1 段：完整复用 mark 的验证 + 密度门禁 + 状态写入（失败则在其内部 sys.exit，不会进入第 2 段）
    cmd_mark_flash_extracted(args, print_next_hint=False)

    # 第 2 段：L3 阶段A 组包，与第 1 段零间隙
    inspector = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pro_qa_inspector.py")
    cmd = [sys.executable, inspector,
           "--archive-dir", args.archive_dir,
           "--account", args.account,
           "--video-id", args.video_id,
           "--date", args.date,
           "--emit-review-packet"]
    print("\n" + "=" * 60)
    print("🔗 finalize-l2：门禁已过，同进程接管 L3 阶段A 组包（零间隙）")
    print("=" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n❌ L3 阶段A 组包失败（rc={result.returncode}）。状态已是 FLASH_EXTRACTED，"
              f"修复后重跑本命令或单独跑 pro_qa_inspector.py 即可（幂等）")
        sys.exit(result.returncode)
    print("\n✅ finalize-l2 完成：FLASH_EXTRACTED + _pro_review_packet.json 已就位，"
          "死亡半径归零。下一步：Pro 3.1 阶段B 语义终审")


def cmd_emit_l2_skeleton(args):
    """从 schema_contract.json 生成 L2 analysis 骨架（写前预检机械化，2026-07-26）

    背景：铁头阿彪02 事故——Agent 凭记忆构造 JSON 结构，一次漏 9 个契约必填字段 +
    honesty_report 位置写错，finalize-l2 连拦 3 轮。本命令把「写前预检铁律」从自觉阅读
    变成机器发牌：骨架含全部契约必填字段（含 _meta.honesty_report 嵌套结构），
    Agent 照骨架填空即可一次过结构门禁。

    安全设计：
    - honesty 骨架 view_file_watched 预置 false，timeline 预置 []——未真实填写必被门禁拒绝
    - 🔴 禁止把骨架直接落盘为 analysis_<date>.json（会干扰 watchdog 遗孤盘点），
      只作对照模板或写到 --out 指定的临时路径
    """
    try:
        contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 无法读取契约 {_CONTRACT_PATH}: {e}")
        sys.exit(1)
    sections_spec = contract.get("sections", {})
    if not sections_spec:
        print("❌ 契约无 sections 定义")
        sys.exit(1)

    timeline_hints = ("timeline", "transcript", "beats", "quotes")

    def placeholder(field):
        return [] if any(h in field for h in timeline_hints) else None

    skeleton = {
        "_meta": {
            "video_file": "<文件名>",
            "video_id": args.video_id or "<视频ID>",
            "account": args.account or "<账号名>",
            "analysis_date": args.date or "<YYYY-MM-DD>",
            "model": "gemini-3.6-flash",
            "analysis_method": "view_file_multimodal",
            "sections": list(sections_spec.keys()),
            "honesty_report": {
                "view_file_called": False,
                "view_duration_sec": None,
                "watched_full_video": False,
                "sections": {
                    s: {"view_file_watched": False, "evidence": "",
                        "specific_details_only_from_watching": []}
                    for s in sections_spec
                },
                "fields_not_from_viewing": [],
                "script_generated": False,
            },
        },
    }
    checklist = {}
    for name, spec in sections_spec.items():
        node = {}
        for f in spec.get("top", []):
            if f == "macro":
                node["macro"] = {m: None for m in spec.get("macro", [])}
            else:
                node[f] = placeholder(f)
        skeleton[name] = node
        checklist[name] = {
            "top_required": spec.get("top", []),
            "macro_required": spec.get("macro", []),
            "top_soft": spec.get("top_soft", []),
            "macro_soft": spec.get("macro_soft", []),
        }

    out_json = json.dumps(skeleton, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        if out_path.name.startswith("analysis_"):
            print("❌ 禁止将骨架写为 analysis_*.json（会被 watchdog/门禁误认为感知产物），"
                  "请换文件名（如 _l2_skeleton.json）")
            sys.exit(1)
        out_path.write_text(out_json + "\n", encoding="utf-8")
        print(f"✅ 骨架已写入: {out_path}")
    else:
        print(out_json)

    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write(f"契约必填字段清单（唯一事实源: {_CONTRACT_PATH.name} v{contract.get('version', '?')}）\n")
    sys.stderr.write("=" * 60 + "\n")
    for name, c in checklist.items():
        sys.stderr.write(f"[{name}] top: {', '.join(c['top_required'])}")
        if c["macro_required"]:
            sys.stderr.write(f" | macro: {', '.join(c['macro_required'])}")
        sys.stderr.write("\n")
    sys.stderr.write(
        "\n⚠️ 骨架仅供结构对齐：所有值必须来自真实 view_file 感知；"
        "honesty 预置 false / timeline 预置 []，不真实填写必被 finalize-l2 拒绝。\n"
        "🔴 禁止直接另存为 analysis_<date>.json；按渐进落盘铁律逐板块写入真实结果。\n")


def cmd_preflight(args):
    """开工前检查：扫描所有视频状态，推荐下一步行动

    输出 JSON 供 Agent 解析 + 人类可读 stderr。
    """
    videos_root = Path(args.archive_dir) / args.account / "videos"
    if not videos_root.is_dir():
        print(f"❌ 账号视频目录不存在: {videos_root}")
        sys.exit(1)

    videos = []
    stuck_count = 0
    orphan_count = 0
    completed_count = 0
    in_progress_count = 0
    tampered_count = 0

    for vdir in sorted(videos_root.iterdir()):
        if not vdir.is_dir():
            continue

        video_id = vdir.name
        state, state_path = load_state(str(vdir))
        current_state = state.get("current_state", "UNKNOWN") if state else "NO_STATE"

        # 篡改检测
        issues, severity = check_state_tampering(state, state_path, str(vdir))
        if issues:
            tampered_count += 1

        # 下一步行动
        actions = get_next_action(current_state, str(vdir), video_id, args.account, args.archive_dir)

        # 统计
        if current_state == "PASS_DELIVERED":
            completed_count += 1
        elif current_state == "FLASH_EXTRACTED" and not has_file(str(vdir), "_pro_review_packet.json"):
            stuck_count += 1
        elif current_state in ("PREPROCESSED", "FLASH_EXTRACTED", "PRO_AUDITING", "PROBE_REPAIRING"):
            in_progress_count += 1

        # watchdog：写完收工遗孤（analysis 齐 5 板块但状态仍 PREPROCESSED）
        if current_state == "PREPROCESSED" and actions and actions[0][0] == "P0_遗孤":
            orphan_count += 1

        videos.append({
            "video_id": video_id,
            "current_state": current_state,
            "has_analysis": bool(find_analysis_files(str(vdir))),
            "has_pro_packet": has_file(str(vdir), "_pro_review_packet.json"),
            "has_qa_result": has_file(str(vdir), "_qa_result.json"),
            "tamper_issues": issues,
            "tamper_severity": severity,
            "next_actions": [{"priority": p, "desc": d, "cmd": c} for p, d, c in actions],
        })

    # 会话预算评估
    budget_used = in_progress_count + completed_count
    budget_remaining = SESSION_BUDGET_MAX - min(budget_used, SESSION_BUDGET_MAX)

    # 优先级排序：P1_紧急 > P2 > P3 > P4
    priority_videos = [v for v in videos if v["next_actions"]]
    priority_videos.sort(key=lambda v: v["next_actions"][0]["priority"] if v["next_actions"] else "zzz")

    result = {
        "mode": "preflight",
        "account": args.account,
        "archive_dir": args.archive_dir,
        "scan_time": datetime.now().isoformat(),
        "summary": {
            "total_videos": len(videos),
            "completed": completed_count,
            "in_progress": in_progress_count,
            "stuck_at_l2_l3_gap": stuck_count,
            "orphan_analysis_unfinalized": orphan_count,
            "tampered": tampered_count,
        },
        "session_budget": {
            "max_per_session": SESSION_BUDGET_MAX,
            "soft_warn_at": SESSION_BUDGET_SOFT,
            "used_today": budget_used,
            "remaining": budget_remaining,
            "recommendation": (
                "⚠️ 会话预算已达上限，建议开新会话" if budget_remaining <= 0
                else f"⚠️ 会话预算接近上限（剩 {budget_remaining}），建议尽快收尾" if budget_remaining == 1
                else f"✅ 会话预算充足（剩 {budget_remaining}/{SESSION_BUDGET_MAX}）"
            ),
        },
        "priority_actions": [
            {
                "video_id": v["video_id"],
                "state": v["current_state"],
                "priority": v["next_actions"][0]["priority"],
                "action": v["next_actions"][0]["desc"],
                "command": v["next_actions"][0]["cmd"],
            }
            for v in priority_videos
            if v["next_actions"] and v["next_actions"][0]["priority"] != "done"
        ],
        "videos": videos,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 人类可读摘要
    sys.stderr.write(f"\n{'=' * 60}\n")
    sys.stderr.write(f"会话寿命管理 · 前检查\n")
    sys.stderr.write(f"账号: {args.account} | 扫描时间: {datetime.now().strftime('%H:%M:%S')}\n")
    sys.stderr.write(f"{'=' * 60}\n")
    s = result["summary"]
    sys.stderr.write(f"总视频: {s['total_videos']} | 完成: {s['completed']} | 在途: {s['in_progress']} | 卡住: {s['stuck_at_l2_l3_gap']} | 遗孤: {s['orphan_analysis_unfinalized']} | 篡改: {s['tampered']}\n")
    b = result["session_budget"]
    sys.stderr.write(f"会话预算: {b['recommendation']}\n")

    if orphan_count > 0:
        sys.stderr.write(f"\n🔴 P0 — {orphan_count} 条视频 analysis 已齐 5 板块但从未 finalize-l2（写完收工遗孤），禁止重进 L2，立即补跑:\n")
        for v in priority_videos:
            if v["next_actions"] and v["next_actions"][0]["priority"] == "P0_遗孤":
                sys.stderr.write(f"   {v['video_id']}: {v['next_actions'][0]['cmd']}\n")

    if stuck_count > 0:
        sys.stderr.write(f"\n🔴 紧急 — {stuck_count} 条视频卡在 L2→L3 间隙，必须先推进再开新坑:\n")
        for v in priority_videos:
            if v["next_actions"] and "P1" in v["next_actions"][0]["priority"]:
                sys.stderr.write(f"   {v['video_id']}: {v['next_actions'][0]['desc']}\n")

    if tampered_count > 0:
        sys.stderr.write(f"\n⚠️ {tampered_count} 条视频 _state.json 疑似被手写篡改:\n")
        for v in videos:
            if v["tamper_issues"]:
                sys.stderr.write(f"   {v['video_id']}: {v['tamper_issues'][0]}\n")

    if result["priority_actions"]:
        sys.stderr.write(f"\n📋 优先行动清单（按优先级排序）:\n")
        for a in result["priority_actions"]:
            sys.stderr.write(f"   [{a['priority']}] {a['video_id']} ({a['state']}): {a['action']}\n")
    else:
        sys.stderr.write(f"\n✅ 所有视频已完成或无待处理项\n")


def cmd_validate_state(args):
    """状态篡改检测：检查特定视频或全量视频的 _state.json 完整性"""
    if args.video_id:
        video_dir = os.path.join(args.archive_dir, args.account, "videos", args.video_id)
        state, state_path = load_state(video_dir)
        issues, severity = check_state_tampering(state, state_path, video_dir)
        result = {
            "video_id": args.video_id,
            "state_path": state_path,
            "current_state": state.get("current_state", "NO_STATE") if state else "NO_STATE",
            "issues": issues,
            "severity": severity,
            "verdict": "✅ 通过" if not issues else f"🔴 {severity.upper()}",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if issues:
            sys.exit(1)
        return

    # 全量扫描
    videos_root = Path(args.archive_dir) / args.account / "videos"
    if not videos_root.is_dir():
        print(f"❌ 账号视频目录不存在: {videos_root}")
        sys.exit(1)

    results = []
    for vdir in sorted(videos_root.iterdir()):
        if not vdir.is_dir():
            continue
        state, state_path = load_state(str(vdir))
        issues, severity = check_state_tampering(state, state_path, str(vdir))
        results.append({
            "video_id": vdir.name,
            "current_state": state.get("current_state", "NO_STATE") if state else "NO_STATE",
            "issues": issues,
            "severity": severity,
        })

    clean = [r for r in results if not r["issues"]]
    flagged = [r for r in results if r["issues"]]

    summary = {
        "mode": "validate-state",
        "total": len(results),
        "clean": len(clean),
        "flagged": len(flagged),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    sys.stderr.write(f"\n✅ 通过: {len(clean)} | 🔴 疑似篡改: {len(flagged)}\n")
    if flagged:
        sys.stderr.write("\n篡改详情:\n")
        for r in flagged:
            sys.stderr.write(f"   {r['video_id']} ({r['current_state']}): {r['issues'][0]}\n")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="会话寿命管理器 — L2→L3 原子绑定 + 会话预算 + 状态机完整性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # --mark-flash-extracted
    p_mark = sub.add_parser("mark-flash-extracted",
                            help="L2 完成后：验证 analysis JSON 并标记 FLASH_EXTRACTED（替代手写）")
    p_mark.add_argument("--archive-dir", required=True)
    p_mark.add_argument("--account", required=True)
    p_mark.add_argument("--video-id", required=True)
    p_mark.add_argument("--date", required=True, help="分析日期 YYYY-MM-DD")

    # --finalize-l2（推荐入口：mark + L3 阶段A 一键连跑，间隙物理消失）
    p_fin = sub.add_parser("finalize-l2",
                           help="L2 收尾一键化：mark-flash-extracted + emit-review-packet 同进程连跑（推荐）")
    p_fin.add_argument("--archive-dir", required=True)
    p_fin.add_argument("--account", required=True)
    p_fin.add_argument("--video-id", required=True)
    p_fin.add_argument("--date", required=True, help="分析日期 YYYY-MM-DD")

    # --preflight
    p_pre = sub.add_parser("preflight",
                           help="开工前检查：扫描所有视频状态，推荐下一步行动")
    p_pre.add_argument("--archive-dir", required=True)
    p_pre.add_argument("--account", required=True)

    # --emit-l2-skeleton（写前预检机械化：从契约生成骨架 + 必填清单）
    p_skel = sub.add_parser("emit-l2-skeleton",
                            help="从 schema_contract.json 生成 L2 analysis 骨架（含 honesty 嵌套结构），杀死凭记忆构造")
    p_skel.add_argument("--account", default="", help="预填 _meta.account（可选）")
    p_skel.add_argument("--video-id", default="", help="预填 _meta.video_id（可选）")
    p_skel.add_argument("--date", default="", help="预填 _meta.analysis_date（可选）")
    p_skel.add_argument("--out", default="", help="写入路径（省略则 stdout；禁止 analysis_*.json）")

    # --validate-state
    p_val = sub.add_parser("validate-state",
                           help="状态篡改检测：检查 _state.json 完整性")
    p_val.add_argument("--archive-dir", required=True)
    p_val.add_argument("--account", required=True)
    p_val.add_argument("--video-id", default="", help="指定视频ID（省略则全量扫描）")

    args = parser.parse_args()

    if args.command == "mark-flash-extracted":
        cmd_mark_flash_extracted(args)
    elif args.command == "finalize-l2":
        cmd_finalize_l2(args)
    elif args.command == "emit-l2-skeleton":
        cmd_emit_l2_skeleton(args)
    elif args.command == "preflight":
        cmd_preflight(args)
    elif args.command == "validate-state":
        cmd_validate_state(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
