#!/bin/zsh
# 全量 L1 批量预处理 runner — 2026-07-26 提速优化建议 1
# 6 个账号顺序跑，日志实时写入归档目录。可重复执行（batch_preprocess.py 幂等跳过）。
export PATH="$HOME/.local/bin:$PATH"
SCRIPTS="{{PROJECT_ROOT}}/scripts"
ARCHIVE="{{MEDIA_DIR}}/analysis_archive"
SRC="{{MEDIA_DIR}}"

# Source: account directory names
run_account() {
  local src_dir="$1" account="$2"
  echo "\n######## $(date '+%F %T') 开始账号: $account ########"
  python3 "$SCRIPTS/batch_preprocess.py" \
    --videos-dir "$SRC/$src_dir" \
    --account "$account" \
    --archive-dir "$ARCHIVE"
}

echo "======== 全量 L1 批次启动 $(date '+%F %T') ========"
run_account "AccountA" "AccountA"
run_account "AccountB" "AccountB"
run_account "AccountC" "AccountC"
run_account "AccountD" "AccountD"
run_account "AccountE" "AccountE"
run_account "AccountF" "AccountF"
echo "\n======== 全量 L1 批次结束 $(date '+%F %T') ========"
