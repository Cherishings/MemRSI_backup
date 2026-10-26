#!/usr/bin/env bash
set -euo pipefail
systemctl --user restart paos-node107-tunnel.service
systemctl --user --no-pager status paos-node107-tunnel.service
