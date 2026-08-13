#!/usr/bin/env python3
"""VO 文本质量深检：台词自然度 + 视频名嵌入 + 跨账号句式雷同。"""
import argparse
import os
import re
from collections import Counter, defaultdict

from local_paths import load_analyses, resolve_archive_dir


def run(all_data):
    print("加载 {0} 个视频\n".format(len(all_data)))

    print("=" * 70)
    print("1. VO 文本视频名/ID 嵌入统计")
    print("=" * 70)

    categories = {
        "含TOP编号": lambda t: bool(re.search(r'TOP\d+', t)),
        "含_01后缀": lambda t: bool(re.search(r'_[0-9]{2}', t)),
        "含POV前缀": lambda t: bool(re.search(r'POV', t)),
        "含成精档案编号": lambda t: bool(re.search(r'成精档案\s*\d{4}', t)),
        "含视频中文标题": None,
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

    print("\n  {0:<25} {1:<6} ".format("账号", "总VO"), end="")
    for cat in categories:
        print("{0:<14}".format(cat), end="")
    print()
    print("  {0}".format("-" * 110))

    for acct in sorted(by_acct.keys()):
        d = by_acct[acct]
        total = d["total"]
        print("  {0:<25} {1:<6} ".format(acct, total), end="")
        for cat in categories:
            count = d["issues"][cat]
            pct = "({0:.0f}%)".format(count / total * 100) if total > 0 else ""
            print("{0}{1:<8} ".format(count, pct), end="")
        print()

    print("\n  各账号问题样本:")
    for acct in sorted(vo_samples.keys()):
        print("\n  {0}:".format(acct))
        for vid, text, issues in vo_samples[acct]:
            print("    [{0}] {1}".format(",".join(issues), text))

    print("\n" + "=" * 70)
    print("2. VO 跨账号高频短语（>10次）")
    print("=" * 70)

    phrase_by_acct = defaultdict(Counter)
    phrase_total = Counter()

    for acct, vid, data in all_data:
        for item in data.get("audio", {}).get("voiceover_transcript", []):
            text = item.get("text", "")
            text_clean = re.sub(r'《[^》]+》', '', text)
            text_clean = re.sub(r'TOP\d+', '', text_clean)
            text_clean = re.sub(r'_[0-9]{2}', '', text_clean)

            for i in range(len(text_clean) - 8):
                p = text_clean[i:i + 8]
                if not any(c in p for c in ['，', '。', '！', '？', '：', '、']):
                    phrase_by_acct[p][acct] += 1
                    phrase_total[p] += 1

    cross_vo = [(p, n) for p, n in phrase_total.most_common(50) if n > 10]
    print("\n  跨账号高频 8 字短语 (>10次): {0} 个".format(len(cross_vo)))
    for phrase, count in cross_vo[:15]:
        accts = set(phrase_by_acct[phrase].keys())
        print("    [{0}次, {1}账号] \"{2}\"".format(count, len(accts), phrase))

    print("\n" + "=" * 70)
    print("3. VO 台词自然度抽检（每账号 3 条）")
    print("=" * 70)

    seen = set()
    for acct, vid, data in all_data:
        if acct in seen:
            continue
        seen.add(acct)
        vos = data.get("audio", {}).get("voiceover_transcript", [])
        print("\n  {0}/{1}:".format(acct, vid))
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
            print("    {0} VO[{1}] {2}".format(natural, i, text[:100]))


def main():
    parser = argparse.ArgumentParser(description="VO 文本质量深检")
    parser.add_argument(
        "--archive-dir",
        default=os.environ.get("ARCHIVE_DIR", ""),
        help="归档根目录（默认 $MEDIA_DIR/analysis_archive）",
    )
    args = parser.parse_args()
    archive = resolve_archive_dir(args.archive_dir or None)
    run(load_analyses(archive))


if __name__ == "__main__":
    main()
