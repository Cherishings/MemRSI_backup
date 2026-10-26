#!/usr/bin/env bash
set -euo pipefail
systemctl --user restart paos-node108-tunnel.service
systemctl --user --no-pager status paos-node108-tunnel.service
