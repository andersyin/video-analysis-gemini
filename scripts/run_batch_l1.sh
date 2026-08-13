#!/usr/bin/env bash
# Full-library L1 batch runner. Idempotent: batch_preprocess.py skips in-progress/done videos.
# Requires MEDIA_DIR (export or local.env). Do not sed-replace this file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/local.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/local.env"
  set +a
fi

if [[ -z "${MEDIA_DIR:-}" ]]; then
  echo "error: MEDIA_DIR is not set. Copy local.env.example to local.env or export MEDIA_DIR." >&2
  exit 1
fi
if [[ "$MEDIA_DIR" == *"{{"* ]]; then
  echo "error: MEDIA_DIR still contains a placeholder: $MEDIA_DIR" >&2
  exit 1
fi

export PATH="${HOME}/.local/bin:${PATH}"
ARCHIVE="${MEDIA_DIR%/}/analysis_archive"
SRC="${MEDIA_DIR%/}"

ACCOUNTS=("AccountA" "AccountB" "AccountC" "AccountD" "AccountE" "AccountF")
if [[ -n "${L1_ACCOUNTS:-}" ]]; then
  # Optional override: L1_ACCOUNTS="AccountA AccountB"
  # shellcheck disable=SC2206
  ACCOUNTS=($L1_ACCOUNTS)
fi

run_account() {
  local src_dir="$1"
  local account="$2"
  printf '\n######## %s 开始账号: %s ########\n' "$(date '+%F %T')" "$account"
  python3 "$SCRIPT_DIR/batch_preprocess.py" \
    --videos-dir "$SRC/$src_dir" \
    --account "$account" \
    --archive-dir "$ARCHIVE"
}

printf '======== 全量 L1 批次启动 %s ========\n' "$(date '+%F %T')"
for account in "${ACCOUNTS[@]}"; do
  run_account "$account" "$account"
done
printf '\n======== 全量 L1 批次结束 %s ========\n' "$(date '+%F %T')"
