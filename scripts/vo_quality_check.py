#!/usr/bin/env python3
"""VO 文本质量深检：台词自然度 + 视频名嵌入 + 跨账号句式雷同。"""
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

# ═══════════════════════════════════════════════════════════════
# 1. VO 视频名/ID 嵌入统计（精确版）
# ═══════════════════════════════════════════════════════════════
print("=" * 70)
print("1. VO 文本视频名/ID 嵌入统计")
print("=" * 70)

categories = {
    "含TOP编号": lambda t: bool(re.search(r'TOP\d+', t)),
    "含_01后缀": lambda t: bool(re.search(r'_[0-9]{2}', t)),
    "含POV前缀": lambda t: bool(re.search(r'POV', t)),
    "含成精档案编号": lambda t: bool(re.search(r'成精档案\s*\d{4}', t)),
    "含视频中文标题": None,  # 动态检测
    "含'关于'+'现场'": lambda t: bool(re.search(r'关于.{2,10}现场', t)),
    "含'看'+'这件事'": lambda t: bool(re.search(r'看.{2,15}这件事', t)),
}

by_acct = defaultdict(lambda: {"total": 0, "issues": Counter()})
vo_samples = defaultdict(list)

for acct, vid, data in all_data:
    parts = vid.split('-', 2)
    vid_title = parts[2] if len(parts) >= 3 else vid
    vid_title_short = vid_title[:4] if len(vid_title) >= 4 else vid_title

    for item in data.get("audio", {}).get("voiceover_transcript", []):
        text = item.get("text", "")
        by_acct[acct]["total"] += 1

        issues_found = []
        for cat, check in categories.items():
            if cat == "含视频中文标题":
                if vid_title_short in text:
                    issues_found.append(cat)
            elif check and check(text):
                issues_found.append(cat)

        for issue in issues_found:
            by_acct[acct]["issues"][issue] += 1

        if issues_found and len(vo_samples[acct]) < 3:
            vo_samples[acct].append((vid, text[:100], issues_found))

print(f"\n  {'账号':<25} {'总VO':<6} ", end="")
for cat in categories:
    print(f"{cat:<14}", end="")
print()
print(f"  {'-'*110}")

for acct in sorted(by_acct.keys()):
    d = by_acct[acct]
    total = d["total"]
    has_any = sum(1 for item in [None] for _ in [None] if any(d["issues"][c] > 0 for c in categories))
    # 计算含任意问题的条数
    print(f"  {acct:<25} {total:<6} ", end="")
    for cat in categories:
        count = d["issues"][cat]
        pct = f"({count/total*100:.0f}%)" if total > 0 else ""
        print(f"{count}{pct:<8} ", end="")
    print()

# 样本
print(f"\n  各账号问题样本:")
for acct in sorted(vo_samples.keys()):
    print(f"\n  {acct}:")
    for vid, text, issues in vo_samples[acct]:
        print(f"    [{','.join(issues)}] {text}")

# ═══════════════════════════════════════════════════════════════
# 2. VO 跨账号句式雷同（8字滑动窗口）
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("2. VO 跨账号高频短语（>10次）")
print("=" * 70)

phrase_by_acct = defaultdict(Counter)
phrase_total = Counter()

for acct, vid, data in all_data:
    for item in data.get("audio", {}).get("voiceover_transcript", []):
        text = item.get("text", "")
        # 去掉视频名
        text_clean = re.sub(r'《[^》]+》', '', text)
        text_clean = re.sub(r'TOP\d+', '', text_clean)
        text_clean = re.sub(r'_[0-9]{2}', '', text_clean)
        
        for i in range(len(text_clean) - 8):
            p = text_clean[i:i+8]
            if not any(c in p for c in ['，', '。', '！', '？', '：', '、']):
                phrase_by_acct[p][acct] += 1
                phrase_total[p] += 1

cross_vo = [(p, n) for p, n in phrase_total.most_common(50) if n > 10]
print(f"\n  跨账号高频 8 字短语 (>10次): {len(cross_vo)} 个")
for phrase, count in cross_vo[:15]:
    accts = set(phrase_by_acct[phrase].keys())
    print(f"    [{count}次, {len(accts)}账号] \"{phrase}\"")

# ═══════════════════════════════════════════════════════════════
# 3. VO 台词自然度抽检
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("3. VO 台词自然度抽检（每账号 3 条）")
print("=" * 70)

seen = set()
for acct, vid, data in all_data:
    if acct in seen:
        continue
    seen.add(acct)
    vos = data.get("audio", {}).get("voiceover_transcript", [])
    print(f"\n  {acct}/{vid}:")
    for i, item in enumerate(vos[:3]):
        text = item.get("text", "")
        natural = "✅" if not any([
            re.search(r'TOP\d+', text),
            re.search(r'_[0-9]{2}', text),
            "POV" in text,
            re.search(r'成精档案\s*\d{4}', text),
            re.search(r'关于.{2,10}现场', text),
            re.search(r'看.{2,15}这件事', text),
        ]) else "❌"
        print(f"    {natural} VO[{i}] {text[:100]}")
