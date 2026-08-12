#!/usr/bin/env python3
"""一体化质量门禁 (Layer 3 物理级硬门禁) —— 整合 schema 验证 + 偷懒检测 + 跨视频雷同检测 + 状态机管理。

每次 Flash 初拆完成后运行此脚本，0 个 🦥 才允许进入 Pro 语义级审查。

用法:
  # 全账号检测
  python unified_gate.py --archive-dir /path/to/archive --account "AccountD"

  # 只检测指定视频（单视频模式）
  python unified_gate.py --archive-dir /path/to/archive --account "AccountD" --videos "vid1,vid2,vid3"

  # 严格模式：唯一率 <80% 也算不通过
  python unified_gate.py --archive-dir /path/to/archive --account "AccountD" --strict

退出码:
  0 = 全部通过（GREEN）
  1 = 有问题（RED），需要修复后重跑
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


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


SECTIONS = _load_sections()


# ═══════════════════════════════════════════════════════════════
# 检测项定义
# ═══════════════════════════════════════════════════════════════

# 软模板动作短语（跨账号重复 ~370 次的 14+3 个短语）
SOFT_TEMPLATE_PHRASES = [
    "伸长脖子凑近镜头", "湿润鼻头特写", "眼睛直钩钩盯着侧面镜头",
    "耳朵微微前竖", "下巴紧贴地面仰视", "用两只前爪捂住面部后快速张开眼睛",
    "在茶几周围踱步转圈", "眼神瞟向零食袋", "跳上沙发挤在两人中间",
    "尾巴快速摆动", "前爪先着地缓冲", "背景呈暖色调灯光",
    "前爪搭上膝盖", "舌头伸出轻轻舔嘴唇",
    "歪着脑袋凝视前方，瞳孔微微放大",
    "急促地划过木地板，身体向前倾斜",
    "头定格不动，眼神直钩钩视向右侧",
]

# 硬模板标记
HARD_TEMPLATE_MARKERS = ["镜头展现", "画面展现", "第N镜"]

# VO 视频名/ID 嵌入检测模式
VO_REF_PATTERNS = [
    (r"TOP\d+", "TOP编号"),
    (r"_[0-9]{2}", "_数字后缀"),
    ("POV", "POV前缀"),
    (r"成精档案\s*\d{4}", "档案编号"),
    (r"关于.{2,10}现场", "关于XXX现场"),
    (r"看.{2,15}这件事", "看XXX这件事"),
]


def strip_vn(text):
    """去掉 《xxx》 视频名前缀。"""
    return re.sub(r"《[^》]+》", "", text).strip()


def load_files(archive_dir, account, video_ids=None):
    """加载指定账号的分析文件。"""
    videos_dir = Path(archive_dir) / account / "videos"
    if not videos_dir.exists():
        return [], f"账号目录不存在: {videos_dir}"

    files = sorted(videos_dir.glob("*/analysis_*.json"))
    if video_ids:
        vid_set = set(video_ids)
        files = [f for f in files if f.parent.name in vid_set]

    results = []
    for f in files:
        try:
            data = json.loads(f.read_text("utf-8"))
            results.append((f.parent.name, f, data))
        except Exception as e:
            results.append((f.parent.name, f, None))

    return results, None


# ═══════════════════════════════════════════════════════════════
# 检测函数
# ═══════════════════════════════════════════════════════════════

def check_hard_templates(all_data):
    """检测硬模板标记（镜头展现等）。"""
    issues = []
    for vid, f, data in all_data:
        if not data:
            continue
        cine = data.get("cinematography", {})
        shots = cine.get("shot_timeline", [])
        count = 0
        for item in shots:
            vc = item.get("visual_content", "")
            if any(m in vc for m in HARD_TEMPLATE_MARKERS):
                count += 1
        if count > 0:
            issues.append(f"  🦥 {vid}: visual_content 硬模板 ({count}/{len(shots)}条)")
    return issues


def check_soft_templates(all_data):
    """检测软模板动作短语。"""
    issues = []
    for vid, f, data in all_data:
        if not data:
            continue
        cine = data.get("cinematography", {})
        shots = cine.get("shot_timeline", [])
        count = 0
        for item in shots:
            vc = item.get("visual_content", "")
            if any(p in vc for p in SOFT_TEMPLATE_PHRASES):
                count += 1
        if count > 0 and count / max(len(shots), 1) > 0.3:
            issues.append(f"  🦥 {vid}: visual_content 软模板 ({count}/{len(shots)}条, {count/max(len(shots),1)*100:.0f}%)")
    return issues


def check_vector_prefix(all_data):
    """检测"SubjectJ"前缀。"""
    issues = []
    for vid, f, data in all_data:
        if not data:
            continue
        cine = data.get("cinematography", {})
        shots = cine.get("shot_timeline", [])
        count = sum(1 for s in shots if "SubjectJ" in s.get("visual_content", ""))
        if count > 0:
            issues.append(f"  🦥 {vid}: 'SubjectJ'前缀 ({count}/{len(shots)}条)")
    return issues


def check_vo_video_name(all_data):
    """检测 VO 文本中的视频名/ID 嵌入。"""
    issues = []
    for vid, f, data in all_data:
        if not data:
            continue
        audio = data.get("audio", {})
        vos = audio.get("voiceover_transcript", [])
        count = 0
        for item in vos:
            text = item.get("text", "")
            for pattern, label in VO_REF_PATTERNS:
                if isinstance(pattern, str):
                    if pattern in text:
                        count += 1
                        break
                else:
                    if re.search(pattern, text):
                        count += 1
                        break
        if count > 0 and count / max(len(vos), 1) > 0.3:
            issues.append(f"  🦥 {vid}: VO视频名嵌入 ({count}/{len(vos)}条, {count/max(len(vos),1)*100:.0f}%)")
    return issues


def check_cross_video_uniqueness(all_data, min_ratio=0.8):
    """检测跨视频字段唯一率。"""
    issues = []
    
    # SFX description
    sfx_cores = []
    vc_cores = []
    vo_prefixes = []
    
    for vid, f, data in all_data:
        if not data:
            continue
        audio = data.get("audio", {})
        cine = data.get("cinematography", {})
        
        for item in audio.get("sfx_timeline", []):
            sfx_cores.append(strip_vn(item.get("description", "")))
        
        for item in cine.get("shot_timeline", []):
            vc = item.get("visual_content", "")
            vc_clean = re.sub(r"【[\d.]+-[\d.]+s】", "", vc)
            vc_cores.append(vc_clean)
        
        for item in audio.get("voiceover_transcript", []):
            vo_prefixes.append(item.get("text", "")[:60])
    
    for name, cores, threshold in [
        ("SFX description", sfx_cores, 0.5),
        ("visual_content", vc_cores, 0.5),
        ("VO开头", vo_prefixes, 0.8),
    ]:
        if len(cores) < 2:
            continue
        unique = len(set(cores))
        ratio = unique / len(cores)
        if ratio < threshold:
            issues.append(f"  🦥 跨视频 {name} 唯一率 {unique}/{len(cores)} ({ratio*100:.1f}%) < {threshold*100:.0f}%")
    
    return issues


def check_shot_density(all_data):
    """检测镜头密度是否达标（含 POV 例外）。"""
    issues = []
    for vid, f, data in all_data:
        if data is None:
            continue
        meta = data.get("_meta", {})
        duration = meta.get("duration_sec", 30)
        cine = data.get("cinematography", {})
        shots = cine.get("shot_timeline", [])
        shot_count = len(shots)

        # 标准要求：每3秒≥1镜，30秒≥10镜
        min_shots_standard = max(6, int(duration / 3))

        # POV 例外：如果诚实度报告中提到 POV/手持长镜头风格，允许降至 ≥6镜/30s
        min_shots = min_shots_standard
        is_pov = False
        hr = meta.get("honesty_report", {})
        # 嵌套 schema（sections.<板块>.evidence）为准，扁平 evidence 为旧版兜底
        evidence_text = json.dumps(hr.get("sections", hr.get("evidence", {})), ensure_ascii=False)
        pov_keywords = ["POV", "第一人称", "手持长镜头", "主观视角", "long take"]
        if any(kw in evidence_text or kw in str(shots) for kw in pov_keywords):
            is_pov = True
            min_shots = max(4, int(duration / 5))  # POV 风格放宽到每5秒≥1镜

        if shot_count < min_shots:
            tag = "POV例外" if is_pov else "标准"
            issues.append(f"  ⚠️ {vid}: 镜头密度 {shot_count}镜/{duration}s < 最低{min_shots}镜 ({tag})")
        elif is_pov and shot_count < min_shots_standard:
            # POV 风格低于标准但达标，给出 info 提示
            pass  # 不报为问题，只是 info

    return issues


def check_sfx_density(all_data):
    """检测 SFX 密度是否达标。"""
    issues = []
    for vid, f, data in all_data:
        if data is None:
            continue
        meta = data.get("_meta", {})
        duration = meta.get("duration_sec", 30)
        audio = data.get("audio", {})
        sfx = audio.get("sfx_timeline", [])
        sfx_count = len(sfx)

        # 标准要求：每10秒≥2个，30秒≥6个
        min_sfx = max(4, int(duration / 10 * 2))

        if sfx_count < min_sfx:
            issues.append(f"  ⚠️ {vid}: SFX 密度 {sfx_count}个/{duration}s < 最低{min_sfx}个")

    return issues


def check_schema_fields(all_data):
    """检测必填字段缺失。"""
    issues = []
    for vid, f, data in all_data:
        if data is None:
            issues.append(f"  ❌ {vid}: JSON 解析失败")
            continue
        
        for section in SECTIONS:
            if section not in data:
                issues.append(f"  ❌ {vid}: 板块 '{section}' 缺失")
    
    return issues


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="一体化质量门禁 — Batch 完成后必须运行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--account", required=True, help="账号名")
    parser.add_argument("--videos", help="只检测指定视频ID（逗号分隔），用于 Batch 模式")
    parser.add_argument("--strict", action="store_true", help="严格模式：唯一率 <80%% 也算不通过")
    args = parser.parse_args()

    video_ids = args.videos.split(",") if args.videos else None
    all_data, err = load_files(args.archive_dir, args.account, video_ids)
    
    if err:
        print(f"❌ {err}")
        sys.exit(1)

    if not all_data:
        print("⚠️ 未找到分析文件")
        sys.exit(1)

    print("=" * 60)
    print(f"Layer 3 物理级硬门禁 (unified_gate)")
    print(f"账号: {args.account}")
    print(f"检测文件: {len(all_data)} 个")
    if video_ids:
        print(f"模式: 单视频检测 ({len(video_ids)} 条视频)")
    print("=" * 60)

    all_issues = []

    # 1. Schema 必填字段
    print("\n1. Schema 必填字段检查...")
    schema_issues = check_schema_fields(all_data)
    all_issues.extend(schema_issues)
    print(f"   {'✅ 通过' if not schema_issues else f'❌ {len(schema_issues)} 个问题'}")

    # 2. 硬模板检测
    print("\n2. 硬模板检测...")
    hard_issues = check_hard_templates(all_data)
    all_issues.extend(hard_issues)
    print(f"   {'✅ 通过' if not hard_issues else f'🦥 {len(hard_issues)} 个问题'}")

    # 3. 软模板检测
    print("\n3. 软模板动作短语检测...")
    soft_issues = check_soft_templates(all_data)
    all_issues.extend(soft_issues)
    print(f"   {'✅ 通过' if not soft_issues else f'🦥 {len(soft_issues)} 个问题'}")

    # 4. "SubjectJ"前缀检测
    print("\n4. 'SubjectJ'前缀检测...")
    vector_issues = check_vector_prefix(all_data)
    all_issues.extend(vector_issues)
    print(f"   {'✅ 通过' if not vector_issues else f'🦥 {len(vector_issues)} 个问题'}")

    # 5. VO 视频名嵌入检测
    print("\n5. VO 视频名/ID 嵌入检测...")
    vo_issues = check_vo_video_name(all_data)
    all_issues.extend(vo_issues)
    print(f"   {'✅ 通过' if not vo_issues else f'🦥 {len(vo_issues)} 个问题'}")

    # 6. 跨视频唯一率
    if len(all_data) >= 2:
        print("\n6. 跨视频唯一率检测...")
        min_ratio = 0.8 if args.strict else 0.5
        cross_issues = check_cross_video_uniqueness(all_data, min_ratio)
        all_issues.extend(cross_issues)
        print(f"   {'✅ 通过' if not cross_issues else f'🦥 {len(cross_issues)} 个问题'}")
    else:
        print("\n6. 跨视频唯一率检测... 跳过（仅1条视频）")

    # 7. 镜头密度检查（含 POV 例外）
    print("\n7. 镜头密度检查...")
    density_issues = check_shot_density(all_data)
    all_issues.extend(density_issues)
    print(f"   {'✅ 通过' if not density_issues else f'⚠️ {len(density_issues)} 个问题'}")

    # 8. SFX 密度检查
    print("\n8. SFX 密度检查...")
    sfx_issues = check_sfx_density(all_data)
    all_issues.extend(sfx_issues)
    print(f"   {'✅ 通过' if not sfx_issues else f'⚠️ {len(sfx_issues)} 个问题'}")

    # 汇总
    print(f"\n{'=' * 60}")
    total_issues = len(all_issues)
    if total_issues == 0:
        print("🟢 GREEN — 物理级硬门禁全部通过，可进入 Pro 语义级审查")
        # 更新状态机：FLASH_EXTRACTED -> PRO_AUDITING（幂等：已处于该状态不重复追加）
        from datetime import datetime
        for vid, f, data in all_data:
            state_path = f.parent / "_state.json"
            state = {}
            if state_path.exists():
                with open(state_path) as sf:
                    state = json.load(sf)
            if state.get("current_state") != "PRO_AUDITING":
                state["current_state"] = "PRO_AUDITING"
                state.setdefault("history", []).append({
                    "state": "PRO_AUDITING",
                    "timestamp": datetime.now().isoformat(),
                    "gate": "unified_gate.py passed",
                })
                with open(state_path, "w") as sf:
                    json.dump(state, sf, ensure_ascii=False, indent=2)
        sys.exit(0)
    else:
        print(f"🔴 RED — {total_issues} 个问题，需要 Flash 修复后重跑")
        for issue in all_issues:
            print(issue)
        # 更新状态机：停留在 FLASH_EXTRACTED，标记需修复
        from datetime import datetime
        for vid, f, data in all_data:
            state_path = f.parent / "_state.json"
            state = {}
            if state_path.exists():
                with open(state_path) as sf:
                    state = json.load(sf)
            state["current_state"] = "FLASH_EXTRACTED"
            state.setdefault("history", []).append({
                "state": "FLASH_EXTRACTED (gate failed)",
                "timestamp": datetime.now().isoformat(),
                "issues": total_issues,
            })
            with open(state_path, "w") as sf:
                json.dump(state, sf, ensure_ascii=False, indent=2)
        sys.exit(1)


if __name__ == "__main__":
    main()
