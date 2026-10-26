#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 3 || ! $1 =~ ^[0-7]$ || ! $2 =~ ^[0-7]$ || ! $3 =~ ^[0-7]$ || $1 == "$2" || $1 == "$3" || $2 == "$3" ]]; then
  echo '用法: bash start.sh GPU_A GPU_B GPU_C（3 张不同的卡，例如 0 6 7）' >&2
  exit 2
fi
# Only validated single-digit IDs enter the remote command; no credentials copied.
ssh xi "/home/xi/envs/agent/bin/python /data/stormlab/xi/paos/worktrees/memrsi-feedback-v1_3/start_v13.py --gpus $1 $2 $3"
