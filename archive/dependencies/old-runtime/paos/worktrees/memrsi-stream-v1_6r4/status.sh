#!/usr/bin/env bash
set -euo pipefail
ssh xi '/home/xi/envs/agent/bin/python /data/stormlab/xi/paos/worktrees/memrsi-feedback-v1_3/status_v13.py'
