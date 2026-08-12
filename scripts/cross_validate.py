#!/usr/bin/env python3
"""交叉验证：多维度自洽性检查。"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ARCHIVE = Path("{{MEDIA_DIR}}/analysis_archive")

all_data = []
for acct_dir in sorted(ARCHIVE.iterdir()):
    if not acct_dir.is_dir() or acct_dir.name.startswith('.'):
        continue
    vd = acct_dir / "videos"
    if not vd.exists():
        continue
    for f in sorted(vd.glob("*/analysis_*.json")):
        try:
            data = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        all_data.append((acct_dir.name, f.parent.name, data))

print(f"加载 {len(all_data)} 个视频\n")


# ═══════════════════════════════════════════════════════════════════
# 1. SFX 时间戳 vs 镜头区间
# ═══════════════════════════════════════════════════════════════════
print("=" * 70)
print("交叉验证 1: SFX 时间戳 vs 镜头区间")
print("=" * 70)

sfx_in_range = 0
sfx_out_range = 0
sfx_details = []

for acct, vid, data in all_data:
    cine = data.get("cinematography", {})
    audio = data.get("audio", {})
    shots = cine.get("shot_timeline", [])
    sfx = audio.get("sfx_timeline", [])
    
    if not shots or not sfx:
        continue
    
    max_shot_end = shots[-1].get("end_sec", 0) if shots else 0
    
    for item in sfx:
        sec = item.get("second", 0)
        if sec > max_shot_end + 0.5:
            sfx_out_range += 1
            if len(sfx_details) < 5:
                sfx_details.append(f"  {acct}/{vid}: SFX {sec}s 超出视频时长 {max_shot_end}s")
        else:
            sfx_in_range += 1

total_sfx = sfx_in_range + sfx_out_range
print(f"  SFX 在范围内: {sfx_in_range}/{total_sfx} ({sfx_in_range/total_sfx*100:.1f}%)")
print(f"  SFX 超出范围: {sfx_out_range}/{total_sfx}")
if sfx_details:
    print(f"  超出样本:")
    for d in sfx_details:
        print(d)


# ═══════════════════════════════════════════════════════════════════
# 2. VO 时间戳 vs 镜头区间
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("交叉验证 2: VO 时间戳 vs 镜头区间")
print("=" * 70)

vo_in_range = 0
vo_out_range = 0
vo_details = []

for acct, vid, data in all_data:
    cine = data.get("cinematography", {})
    audio = data.get("audio", {})
    shots = cine.get("shot_timeline", [])
    vos = audio.get("voiceover_transcript", [])
    
    if not shots or not vos:
        continue
    
    max_shot_end = shots[-1].get("end_sec", 0) if shots else 0
    
    for item in vos:
        start = item.get("start_sec", 0)
        end = item.get("end_sec", 0)
        if end > max_shot_end + 0.5:
            vo_out_range += 1
            if len(vo_details) < 5:
                vo_details.append(f"  {acct}/{vid}: VO {start}-{end}s 超出 {max_shot_end}s")
        else:
            vo_in_range += 1

total_vo = vo_in_range + vo_out_range
if total_vo > 0:
    print(f"  VO 在范围内: {vo_in_range}/{total_vo} ({vo_in_range/total_vo*100:.1f}%)")
    print(f"  VO 超出范围: {vo_out_range}/{total_vo}")
if vo_details:
    print(f"  超出样本:")
    for d in vo_details:
        print(d)


# ═══════════════════════════════════════════════════════════════════
# 3. BGM 变化点 vs 情绪时间轴对齐
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("交叉验证 3: BGM 变化点 vs 情绪时间轴")
print("=" * 70)

bgm_emo_aligned = 0
bgm_emo_misaligned = 0
bgm_emo_details = []

for acct, vid, data in all_data:
    audio = data.get("audio", {})
    narr = data.get("narrative", {})
    bgm = audio.get("bgm_timeline", [])
    emo = narr.get("emotional_timeline", [])
    
    if not bgm or not emo:
        continue
    
    # 检查每个 BGM 变化点是否在某个情绪段落的时间范围内
    for item in bgm:
        sec = item.get("second", 0)
        found = False
        for seg in emo:
            seg_start = seg.get("start_sec", 0)
            seg_end = seg.get("end_sec", 0)
            if seg_start - 2 <= sec <= seg_end + 2:
                found = True
                bgm_emo_aligned += 1
                break
        if not found:
            bgm_emo_misaligned += 1
            if len(bgm_emo_details) < 5:
                bgm_emo_details.append(f"  {acct}/{vid}: BGM {sec}s 不在任何情绪段内")

total_bm = bgm_emo_aligned + bgm_emo_misaligned
if total_bm > 0:
    print(f"  BGM-情绪对齐: {bgm_emo_aligned}/{total_bm} ({bgm_emo_aligned/total_bm*100:.1f}%)")
    print(f"  BGM-情绪错位: {bgm_emo_misaligned}/{total_bm}")
if bgm_emo_details:
    print(f"  错位样本:")
    for d in bgm_emo_details:
        print(d)


# ═══════════════════════════════════════════════════════════════════
# 4. visual_content vs shot_type 一致性
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("交叉验证 4: visual_content 描述 vs shot_type 字段")
print("=" * 70)

vc_type_match = 0
vc_type_mismatch = 0
vc_type_details = []

for acct, vid, data in all_data:
    cine = data.get("cinematography", {})
    shots = cine.get("shot_timeline", [])
    
    for item in shots:
        vc = item.get("visual_content", "")
        st = item.get("shot_type", "")
        
        # 检查 VC 中是否提到与 shot_type 一致的镜头类型
        vc_lower = vc.lower()
        match = False
        
        if st == "close_up" and ("特写" in vc or "近景" in vc or "close" in vc_lower):
            match = True
        elif st == "medium" and ("中景" in vc or "medium" in vc_lower or "近景" in vc):
            match = True
        elif st == "wide" and ("全景" in vc or "远景" in vc or "wide" in vc_lower):
            match = True
        elif st == "extreme_close_up" and ("特写" in vc or "微距" in vc):
            match = True
        elif st == "over_the_shoulder" and ("过肩" in vc):
            match = True
        elif st == "pov" and ("POV" in vc or "主观" in vc or "第一人称" in vc):
            match = True
        elif not st:
            match = True  # 无 shot_type 不检查
        else:
            # 其他类型只要 VC 中有镜头描述词就算匹配
            if any(w in vc for w in ["特写", "近景", "中景", "全景", "远景", "俯拍", "仰拍"]):
                match = True
        
        if match:
            vc_type_match += 1
        else:
            vc_type_mismatch += 1
            if len(vc_type_details) < 10:
                vc_type_details.append(f"  {acct}/{vid}: shot_type={st} but VC='{vc[:60]}'")

total_vt = vc_type_match + vc_type_mismatch
if total_vt > 0:
    print(f"  VC-shot_type 一致: {vc_type_match}/{total_vt} ({vc_type_match/total_vt*100:.1f}%)")
    print(f"  VC-shot_type 不一致: {vc_type_mismatch}/{total_vt}")
if vc_type_details:
    print(f"  不一致样本:")
    for d in vc_type_details:
        print(d)


# ═══════════════════════════════════════════════════════════════════
# 5. visual_content 句式雷同度量化
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("交叉验证 5: visual_content 句式雷同度")
print("=" * 70)

# 提取句式模板（去掉角色名、场景名等变量，只保留结构词）
def extract_template(vc):
    # 去掉时间戳
    vc = re.sub(r'【[\d.]+-[\d.]+s】', '', vc)
    # 去掉括号内容（角色名品种等）
    vc = re.sub(r'（[^）]*）', '', vc)
    # 提取结构词：镜头类型 + 运镜方式
    m = re.search(r'(特写|近景|中景|全景|远景|俯拍|仰拍|跟拍)', vc)
    lens = m.group(1) if m else ""
    m2 = re.search(r'(固定切镜|手持跟随|手持|固定|跟随|横移|竖移|变焦)', vc)
    move = m2.group(1) if m2 else ""
    return f"{lens}+{move}"

template_counter = Counter()
acct_templates = defaultdict(Counter)
for acct, vid, data in all_data:
    cine = data.get("cinematography", {})
    for item in cine.get("shot_timeline", []):
        vc = item.get("visual_content", "")
        tmpl = extract_template(vc)
        template_counter[tmpl] += 1
        acct_templates[acct][tmpl] += 1

print(f"\n  全局句式 Top 10:")
for tmpl, count in template_counter.most_common(10):
    if count > 10:
        print(f"    [{count}次] {tmpl}")

print(f"\n  各账号主导句式:")
for acct in sorted(acct_templates.keys()):
    top_tmpl, top_count = acct_templates[acct].most_common(1)[0]
    total = sum(acct_templates[acct].values())
    pct = top_count / total * 100
    print(f"    {acct}: '{top_tmpl}' {top_count}/{total} ({pct:.0f}%)")
