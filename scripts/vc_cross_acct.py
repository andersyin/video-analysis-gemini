#!/usr/bin/env python3
"""跨账号 VC 描述相似度检测：去掉角色名/品种后，比较动作描述是否雷同。"""
import argparse
import os
import re
from collections import Counter, defaultdict

from local_paths import load_analyses, resolve_archive_dir


def normalize_vc(vc):
    """去掉时间戳、括号内容（角色名品种）、镜头类型前缀，只保留核心动作描述。"""
    vc = re.sub(r'【[\d.]+-[\d.]+s】', '', vc)
    vc = re.sub(r'（[^）]*）', '', vc)
    vc = re.sub(r'^(贴地平视)?(微俯视|平视|仰视|俯拍)?(特写|近景|中景|全景|远景)?(构图)?', '', vc)
    vc = re.sub(r'（[^）]*）', '', vc)
    vc = re.sub(r'[（(]固定切镜|手持跟随[）)]', '', vc)
    vc = re.sub(r'[（(][^）)]*[）)]', '', vc)
    vc = re.sub(r'(在车内驾驶座|在地毯边|在卧室门口|在沙发|在茶几|在客厅|在厨房|在窗台|在床)', '在X', vc)
    vc = re.sub(
        r'(SubjectA|SubjectB|SubjectC|SubjectD|SubjectE|AccountC|SubjectF|'
        r'SubjectG|SubjectH|SubjectI|SubjectJ|白色小狗|主人|黑白猫咪|棕色腊肠犬|'
        r'英短蓝白猫|棕白田园犬|橘猫|金发女生|约会男生)',
        'SUBJECT',
        vc,
    )
    vc = re.sub(
        r'(伸长脖子凑近镜头，湿润鼻头特写|在X周围踱步转圈，眼神瞟向零食袋|'
        r'前爪先着地缓冲，背景呈暖色调灯光|前爪搭上膝盖，舌头伸出轻轻舔嘴唇|'
        r'跳上沙发挤在两人中间，尾巴快速摆动|眼睛直钩钩盯着侧面镜头，耳朵微微前竖)',
        'ACTION',
        vc,
    )
    return vc.strip()


def run(all_data):
    print("加载 {0} 个视频\n".format(len(all_data)))

    print("=" * 70)
    print("1. 跨账号动作短语重复检测")
    print("=" * 70)

    action_phrases = []
    for acct, vid, data in all_data:
        cine = data.get("cinematography", {})
        for i, item in enumerate(cine.get("shot_timeline", [])):
            vc = item.get("visual_content", "")
            action = normalize_vc(vc)
            action_phrases.append((acct, vid, i, vc, action))

    action_counter = Counter(a[4] for a in action_phrases)
    cross_acct_actions = [(a, n) for a, n in action_counter.most_common(50) if n > 5]

    print("\n  总 VC: {0}".format(len(action_phrases)))
    print("\n  跨账号重复动作短语 (>5次):")
    for action, count in cross_acct_actions[:15]:
        if action.strip():
            accts = set(a[0] for a in action_phrases if a[4] == action)
            print("    [{0}次, {1}账号] \"{2}\"".format(count, len(accts), action[:80]))

    print("\n" + "=" * 70)
    print("2. 8字滑动窗口跨账号重复")
    print("=" * 70)

    phrase_by_acct = defaultdict(Counter)
    phrase_total = Counter()

    for acct, vid, idx, vc, _ in action_phrases:
        raw = re.sub(r'【[\d.]+-[\d.]+s】', '', vc)
        raw = re.sub(r'（[^）]*）', '', raw)
        for i in range(len(raw) - 8):
            p = raw[i:i + 8]
            if any(c in p for c in [' ', '：', '，', '。', '（', '）']):
                continue
            phrase_by_acct[p][acct] += 1
            phrase_total[p] += 1

    cross_phrases = [(p, n) for p, n in phrase_total.most_common(50) if n > 20]
    print("\n  跨账号高频 8 字短语 (>20次):")
    for phrase, count in cross_phrases[:20]:
        accts = set(phrase_by_acct[phrase].keys())
        print("    [{0}次, {1}账号] \"{2}\"".format(count, len(accts), phrase))

    print("\n" + "=" * 70)
    print("3. 跨账号完全相同动作描述（去角色名后）")
    print("=" * 70)

    action_by_acct = defaultdict(lambda: defaultdict(list))
    for acct, vid, idx, vc, action in action_phrases:
        if len(action) > 5:
            action_by_acct[action][acct].append((vid, idx))

    cross_acct_dups = []
    for action, acct_map in action_by_acct.items():
        if len(acct_map) > 1:
            total = sum(len(v) for v in acct_map.values())
            cross_acct_dups.append((action, total, len(acct_map), acct_map))

    cross_acct_dups.sort(key=lambda x: -x[1])
    print("\n  跨账号相同动作描述: {0} 组".format(len(cross_acct_dups)))
    print("\n  Top 15:")
    for action, total, n_accts, acct_map in cross_acct_dups[:15]:
        print("    [{0}条, {1}账号] \"{2}\"".format(total, n_accts, action[:80]))
        for acct, entries in sorted(acct_map.items()):
            sample = entries[0]
            print("      {0}: {1} 镜{2}".format(acct, sample[0], sample[1] + 1))


def main():
    parser = argparse.ArgumentParser(description="跨账号 VC 描述相似度检测")
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
