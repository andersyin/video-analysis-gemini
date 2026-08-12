#!/bin/zsh
# 全量 L1 批量预处理 runner — 2026-07-26 提速优化建议 1
# 6 个账号顺序跑，日志实时写入归档目录。可重复执行（batch_preprocess.py 幂等跳过）。
export PATH="$HOME/.local/bin:$PATH"
SCRIPTS="{{KB_BASE}}/raw/skills/内容平台/video-analysis-gemini/scripts"
ARCHIVE="{{MEDIA_DIR}}/竞品研究/对标视频分析资产"
SRC="{{MEDIA_DIR}}/竞品研究"

# 源目录:归档账号名（主人必须屎源目录带（2.5）后缀）
run_account() {
  local src_dir="$1" account="$2"
  echo "\n######## $(date '+%F %T') 开始账号: $account ########"
  python3 "$SCRIPTS/batch_preprocess.py" \
    --videos-dir "$SRC/$src_dir" \
    --account "$account" \
    --archive-dir "$ARCHIVE"
}

echo "======== 全量 L1 批次启动 $(date '+%F %T') ========"
run_account "铁头阿彪" "铁头阿彪"
run_account "主人必须屎（2.5）" "主人必须屎"
run_account "奶糕成精档案社" "奶糕成精档案社"
run_account "kat-and-oliver" "kat-and-oliver"
run_account "羊和狗刻" "羊和狗刻"
run_account "jiayitsui 碎嘴 naomi" "jiayitsui 碎嘴 naomi"
echo "\n======== 全量 L1 批次结束 $(date '+%F %T') ========"
